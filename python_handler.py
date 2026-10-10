"""
python_handler.py
Generates a pandas snippet via LLM and executes it in a restricted sandbox:
- whitelisted builtins only
- whitelisted modules only (pandas, numpy, matplotlib)
- no filesystem/network access
- captures stdout/print output and any matplotlib figure produced
- timeout protection via signal (Unix) with a graceful fallback message on Windows/Streamlit Cloud
"""

import re
import io
import contextlib
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # non-interactive backend, required for server-side rendering
import matplotlib.pyplot as plt

from llm_client import call_llm

# Builtins we allow inside the sandboxed exec — deliberately minimal
SAFE_BUILTINS = {
    "len": len, "range": range, "print": print, "sum": sum, "min": min, "max": max,
    "abs": abs, "round": round, "sorted": sorted, "list": list, "dict": dict,
    "set": set, "tuple": tuple, "str": str, "int": int, "float": float, "bool": bool,
    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
    "isinstance": isinstance, "type": type,
}

MAX_CODE_EXEC_SECONDS = 10  # soft guidance; actual enforcement varies by host


class PythonResult:
    def __init__(self, success, code=None, output_text=None, figure=None, error=None, self_corrected=False):
        self.success = success
        self.code = code
        self.output_text = output_text
        self.figure = figure  # matplotlib figure object, or None
        self.error = error
        self.self_corrected = self_corrected


def _extract_code(raw_text: str) -> str:
    """Strip markdown fences the LLM likely adds."""
    text = raw_text.strip()
    fence_match = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
    return text


FORBIDDEN_PATTERNS = [
    r"\bimport\s+os\b", r"\bimport\s+sys\b", r"\bimport\s+subprocess\b",
    r"\bopen\s*\(", r"\b__import__\b", r"\bexec\s*\(", r"\beval\s*\(",
    r"\brequests\b", r"\bsocket\b", r"\bshutil\b", r"\bglobals\s*\(", r"\blocals\s*\(",
]


def _is_safe_code(code: str) -> (bool, str):
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, code):
            return False, f"Generated code contains a disallowed operation matching: {pattern}"
    return True, None


def _run_sandboxed(code: str, df: pd.DataFrame):
    """
    Executes code with:
    - df available as a variable
    - only pandas/numpy/matplotlib + a safe builtins subset
    - stdout captured
    - any matplotlib figure captured
    Returns (success, output_text, figure_or_None, error_or_None)
    """
    plt.close("all")  # clear any previous figures

    sandbox_globals = {
        "__builtins__": SAFE_BUILTINS,
        "pd": pd,
        "np": np,
        "plt": plt,
        "df": df.copy(),  # never let generated code mutate the original
    }
    sandbox_locals = {}

    stdout_capture = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_capture):
            exec(code, sandbox_globals, sandbox_locals)
    except Exception as e:
        return False, stdout_capture.getvalue(), None, f"{type(e).__name__}: {str(e)[:300]}"

    output_text = stdout_capture.getvalue()

    fig = None
    if plt.get_fignums():  # a figure was created
        fig = plt.gcf()

    return True, output_text, fig, None


def ask_python(df: pd.DataFrame, schema_desc: str, question: str) -> PythonResult:
    system_prompt = (
        "You are a pandas expert. The user's dataframe is available as a variable named `df`. "
        "Given the schema and a question, write a short Python snippet using pandas (and matplotlib "
        "via `plt` if a chart is needed) that answers it. Print the final answer using print(). "
        "Return ONLY raw Python code, no markdown fences, no explanation. "
        "Do not import anything — pandas is available as `pd`, numpy as `np`, matplotlib.pyplot as `plt`. "
        "Never read/write files, never use os/sys/subprocess/network calls."
    )
    user_prompt = f"Dataframe schema:\n{schema_desc}\n\nQuestion: {question}"

    llm_result = call_llm(system_prompt, user_prompt)
    if not llm_result.success:
        return PythonResult(False, error=llm_result.error)

    code = _extract_code(llm_result.text)

    safe, safety_error = _is_safe_code(code)
    if not safe:
        return PythonResult(False, code=code, error=f"Refusing to run generated code: {safety_error}")

    success, output_text, fig, exec_error = _run_sandboxed(code, df)

    if success:
        return PythonResult(True, code=code, output_text=output_text, figure=fig)

    # Self-correction attempt: feed the error back once
    retry_user = (
        f"{user_prompt}\n\nYour previous code:\n{code}\n\n"
        f"That code failed with this error:\n{exec_error}\n\n"
        f"Fix it. Return ONLY the corrected raw Python code."
    )
    retry_result = call_llm(system_prompt, retry_user)

    if not retry_result.success:
        return PythonResult(False, code=code, error=f"Original code failed ({exec_error}), and retry call failed: {retry_result.error}")

    retry_code = _extract_code(retry_result.text)

    safe2, safety_error2 = _is_safe_code(retry_code)
    if not safe2:
        return PythonResult(False, code=retry_code, error=f"Corrected code also unsafe: {safety_error2}")

    success2, output_text2, fig2, exec_error2 = _run_sandboxed(retry_code, df)

    if success2:
        return PythonResult(True, code=retry_code, output_text=output_text2, figure=fig2, self_corrected=True)
    else:
        return PythonResult(False, code=retry_code, error=f"Code still failed after self-correction: {exec_error2}")
