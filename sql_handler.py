"""
sql_handler.py
Loads a dataframe into an in-memory SQLite table, asks the LLM to write SQL
against the real schema, executes it, and self-corrects once if it errors.
"""

import sqlite3
import pandas as pd
import re
from llm_client import call_llm

TABLE_NAME = "data"


class SQLResult:
    def __init__(self, success, query=None, result_df=None, error=None, explanation=None, self_corrected=False):
        self.success = success
        self.query = query
        self.result_df = result_df
        self.error = error
        self.explanation = explanation
        self.self_corrected = self_corrected


def _clean_sql(raw_text: str) -> str:
    """LLMs often wrap SQL in markdown fences or add commentary — strip that."""
    text = raw_text.strip()
    # Remove ```sql ... ``` or ``` ... ``` fences
    fence_match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
    # If there's still explanatory text before/after, try to isolate the first SQL statement
    # Take everything up to the first semicolon if one exists
    if ";" in text:
        text = text.split(";")[0] + ";"
    return text.strip()


def _is_safe_query(query: str) -> bool:
    """Block anything that isn't a read-only SELECT — this is a read/analyze tool, not an editor."""
    lowered = query.strip().lower()
    if not lowered.startswith("select"):
        return False
    forbidden = ["drop ", "delete ", "insert ", "update ", "alter ", "attach ", "pragma "]
    return not any(word in lowered for word in forbidden)


def _execute_query(conn, query: str):
    """Returns (success, result_df_or_None, error_or_None)"""
    try:
        result_df = pd.read_sql_query(query, conn)
        return True, result_df, None
    except Exception as e:
        return False, None, str(e)[:300]


def ask_sql(df: pd.DataFrame, schema_desc: str, question: str) -> SQLResult:
    # Load data into a fresh in-memory SQLite DB
    conn = sqlite3.connect(":memory:")
    df.to_sql(TABLE_NAME, conn, index=False, if_exists="replace")

    system_prompt = (
        f"You are a SQL expert. The user's data is in a SQLite table named '{TABLE_NAME}'. "
        f"Given the schema and a question, write ONE valid SQLite SELECT query that answers it. "
        f"Return ONLY the raw SQL query, no explanation, no markdown fences, no commentary. "
        f"Only SELECT statements are allowed — never modify data."
    )
    user_prompt = f"Table schema ({TABLE_NAME}):\n{schema_desc}\n\nQuestion: {question}"

    llm_result = call_llm(system_prompt, user_prompt)
    if not llm_result.success:
        conn.close()
        return SQLResult(False, error=llm_result.error)

    query = _clean_sql(llm_result.text)

    if not _is_safe_query(query):
        conn.close()
        return SQLResult(False, error="Generated query wasn't a safe read-only SELECT — refusing to run it. Try rephrasing your question.")

    success, result_df, exec_error = _execute_query(conn, query)

    if success:
        conn.close()
        return SQLResult(True, query=query, result_df=result_df)

    # Self-correction attempt: feed the error back once
    retry_system = system_prompt
    retry_user = (
        f"{user_prompt}\n\nYour previous query:\n{query}\n\n"
        f"That query failed with this error:\n{exec_error}\n\n"
        f"Fix the query. Return ONLY the corrected raw SQL."
    )
    retry_result = call_llm(retry_system, retry_user)

    if not retry_result.success:
        conn.close()
        return SQLResult(False, query=query, error=f"Original query failed ({exec_error}), and retry call failed: {retry_result.error}")

    retry_query = _clean_sql(retry_result.text)

    if not _is_safe_query(retry_query):
        conn.close()
        return SQLResult(False, query=retry_query, error="Corrected query wasn't a safe read-only SELECT either — try rephrasing your question.")

    success2, result_df2, exec_error2 = _execute_query(conn, retry_query)
    conn.close()

    if success2:
        return SQLResult(True, query=retry_query, result_df=result_df2, self_corrected=True)
    else:
        return SQLResult(
            False,
            query=retry_query,
            error=f"Query still failed after self-correction attempt: {exec_error2}"
        )
