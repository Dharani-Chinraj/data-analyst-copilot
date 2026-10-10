"""
Data Analyst Copilot — v1
Upload CSV/Excel, get Excel formulas, SQL queries, or Python analysis.
"""

import streamlit as st
from dotenv import load_dotenv

from data_handler import (
    check_file_size, parse_csv, parse_excel, get_excel_sheet_names,
    clean_and_validate, get_schema_description, MAX_FILE_SIZE_MB, MAX_ROWS_PREVIEW
)
from llm_client import call_llm
from sql_handler import ask_sql
from python_handler import ask_python

load_dotenv()

st.set_page_config(page_title="Data Analyst Copilot", page_icon="📊", layout="wide")
# --- PASTE THIS RIGHT AFTER st.set_page_config(...) IN app.py ---

st.markdown("""
<link rel="manifest" href="./app/static/manifest.json">
<meta name="theme-color" content="#6C5CE7">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="DataCopilot">
<link rel="apple-touch-icon" href="./app/static/icon-192.png">

<style>
/* Tighter, card-like layout */
.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 900px;
}

/* Title styling */
h1 {
    font-weight: 800 !important;
    letter-spacing: -0.5px;
}

/* File uploader card */
[data-testid="stFileUploaderDropzone"] {
    border: 2px dashed #6C5CE7 !important;
    border-radius: 14px !important;
    background: rgba(108, 92, 231, 0.06) !important;
}

/* Tabs styling - bigger touch targets for mobile */
[data-baseweb="tab-list"] {
    gap: 4px;
}
[data-baseweb="tab"] {
    padding: 10px 18px !important;
    border-radius: 10px 10px 0 0 !important;
    font-weight: 600 !important;
}

/* Buttons */
.stButton button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    padding: 0.55rem 1.4rem !important;
    width: 100%;
}

/* Dataframe / preview rounding */
[data-testid="stDataFrame"] {
    border-radius: 10px;
    overflow: hidden;
}

/* Success/info/warning boxes - rounder, tighter */
[data-testid="stAlert"] {
    border-radius: 10px !important;
}

/* Mobile responsiveness */
@media (max-width: 640px) {
    .block-container {
        padding-left: 1rem;
        padding-right: 1rem;
    }
    h1 {
        font-size: 1.6rem !important;
    }
    [data-baseweb="tab"] {
        padding: 8px 10px !important;
        font-size: 0.85rem !important;
    }
}
</style>
""", unsafe_allow_html=True)

# --- END PASTE ---

# ---------- Session state init ----------
if "df" not in st.session_state:
    st.session_state.df = None
if "schema_desc" not in st.session_state:
    st.session_state.schema_desc = None
if "filename" not in st.session_state:
    st.session_state.filename = None


st.title("📊 Data Analyst Copilot")
st.caption("Upload a CSV or Excel file → get Excel formulas, SQL queries, or Python analysis. Free, no signup required.")

# ---------- File upload ----------
uploaded_file = st.file_uploader("Upload your dataset", type=["csv", "xlsx", "xls"])

if uploaded_file is not None:
    ok_size, size_mb = check_file_size(uploaded_file)

    if not ok_size:
        st.error(f"File is {size_mb}MB — this demo caps uploads at {MAX_FILE_SIZE_MB}MB to keep things fast. Try a smaller sample of your data.")
    else:
        file_ext = uploaded_file.name.split(".")[-1].lower()

        if file_ext == "csv":
            result = parse_csv(uploaded_file)
        else:
            # Check for multiple sheets first
            sheet_names = get_excel_sheet_names(uploaded_file)
            chosen_sheet = None
            if sheet_names and len(sheet_names) > 1:
                chosen_sheet = st.selectbox("This file has multiple sheets — pick one:", sheet_names)
            uploaded_file.seek(0)  # reset pointer after sheet-name read
            result = parse_excel(uploaded_file, sheet_name=chosen_sheet)

        if not result.success:
            st.error(f"⚠️ {result.error}")
        else:
            if result.warning:
                st.warning(result.warning)

            df, clean_warnings = clean_and_validate(result.df)
            for w in clean_warnings:
                st.info(f"ℹ️ {w}")

            st.session_state.df = df
            st.session_state.schema_desc = get_schema_description(df)
            st.session_state.filename = uploaded_file.name

            st.success(f"Loaded **{uploaded_file.name}** — {df.shape[0]} rows × {df.shape[1]} columns")

            with st.expander("Preview data", expanded=True):
                st.dataframe(df.head(MAX_ROWS_PREVIEW))
                st.caption(f"Columns: {', '.join(df.columns.astype(str))}")


st.divider()

# ---------- Mode tabs ----------
tab_excel, tab_sql, tab_python = st.tabs(["📗 Excel Formula", "🗄️ SQL Query", "🐍 Python Analysis"])

with tab_excel:
    st.subheader("Get an Excel formula for your question")
    if st.session_state.df is None:
        st.info("Upload a file above first.")
    else:
        question = st.text_input(
            "What do you want to calculate?",
            placeholder="e.g. Get the average of column 'Sales' where 'Region' is 'South'",
            key="excel_question"
        )
        if st.button("Generate formula", key="excel_btn"):
            if not question.strip():
                st.warning("Type a question first.")
            else:
                with st.spinner("Thinking..."):
                    system_prompt = (
                        "You are an Excel formula expert. Given a dataset schema and a user question, "
                        "return ONLY: 1) the Excel formula, 2) a one-sentence plain-English explanation. "
                        "Assume data starts at row 2 (row 1 = headers). Be concise. "
                        "If the question cannot be answered from the given columns, say so clearly instead of guessing."
                    )
                    user_prompt = (
                        f"Dataset columns and sample values:\n{st.session_state.schema_desc}\n\n"
                        f"Question: {question}"
                    )
                    result = call_llm(system_prompt, user_prompt)

                if not result.success:
                    st.error(f"⚠️ {result.error}")
                else:
                    st.markdown(result.text)

with tab_sql:
    st.subheader("Get a SQL query for your question")
    if st.session_state.df is None:
        st.info("Upload a file above first.")
    else:
        sql_question = st.text_input(
            "What do you want to know?",
            placeholder="e.g. Show total sales by region, sorted highest to lowest",
            key="sql_question"
        )
        if st.button("Generate & run SQL", key="sql_btn"):
            if not sql_question.strip():
                st.warning("Type a question first.")
            else:
                with st.spinner("Writing and running SQL..."):
                    result = ask_sql(st.session_state.df, st.session_state.schema_desc, sql_question)

                if not result.success:
                    st.error(f"⚠️ {result.error}")
                    if result.query:
                        st.code(result.query, language="sql")
                else:
                    if result.self_corrected:
                        st.info("ℹ️ First attempt had an error — this query was auto-corrected.")
                    st.code(result.query, language="sql")
                    st.dataframe(result.result_df)

with tab_python:
    st.subheader("Get a Python (pandas) analysis")
    if st.session_state.df is None:
        st.info("Upload a file above first.")
    else:
        py_question = st.text_input(
            "What analysis do you want?",
            placeholder="e.g. Plot the distribution of 'Age' as a histogram",
            key="python_question"
        )
        if st.button("Generate & run Python", key="python_btn"):
            if not py_question.strip():
                st.warning("Type a question first.")
            else:
                with st.spinner("Writing and running Python..."):
                    result = ask_python(st.session_state.df, st.session_state.schema_desc, py_question)

                if not result.success:
                    st.error(f"⚠️ {result.error}")
                    if result.code:
                        st.code(result.code, language="python")
                else:
                    if result.self_corrected:
                        st.info("ℹ️ First attempt had an error — this code was auto-corrected.")
                    st.code(result.code, language="python")
                    if result.output_text and result.output_text.strip():
                        st.text(result.output_text)
                    if result.figure is not None:
                        st.pyplot(result.figure)


st.divider()
st.caption("Built with Streamlit + Groq · Free tier, no subscriptions")
