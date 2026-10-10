# 📊 Data Analyst Copilot

A free, no-subscription web app that turns plain-English questions about your dataset into Excel formulas, SQL queries, or Python analysis.

## Features (v1 — in progress)
- ✅ Upload CSV or Excel (multi-sheet supported)
- ✅ Robust parsing: handles encoding issues, empty rows/columns, malformed files gracefully
- ✅ Excel Formula mode — describe what you want, get the formula + explanation
- 🚧 SQL Query mode — coming next (in-memory SQLite + self-correcting queries)
- 🚧 Python Analysis mode — coming next (sandboxed pandas execution)

## Tech Stack
- **Frontend/Backend**: Streamlit
- **Data handling**: pandas
- **LLM**: Groq (free tier, `llama-3.3-70b-versatile`)
- **Deployment**: Streamlit Community Cloud

## Setup
1. Clone this repo
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your free Groq API key (get one at console.groq.com)
4. `streamlit run app.py`

## Known limitations (v1)
- File size capped at 10MB for demo purposes
- CSV/Excel only — PDF support planned for a later version
- Free-tier LLM API means occasional rate limits under heavy use

## Author
Built by Dharani as a portfolio project demonstrating Excel, SQL, and Python skills in one tool.
