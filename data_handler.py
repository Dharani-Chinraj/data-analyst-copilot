"""
data_handler.py
Handles file upload parsing (CSV + Excel) with graceful error handling.
Goal: never crash, always return either a usable dataframe or a clear message.
"""

import pandas as pd
import io


class ParseResult:
    """Simple container so the app always gets a predictable shape back."""
    def __init__(self, success, df=None, error=None, sheet_names=None, warning=None):
        self.success = success
        self.df = df
        self.error = error
        self.sheet_names = sheet_names  # only set for multi-sheet Excel
        self.warning = warning


MAX_FILE_SIZE_MB = 10
MAX_ROWS_PREVIEW = 10


def check_file_size(uploaded_file):
    """Returns (ok: bool, size_mb: float)"""
    size_mb = uploaded_file.size / (1024 * 1024)
    return size_mb <= MAX_FILE_SIZE_MB, round(size_mb, 2)


def parse_csv(uploaded_file):
    """Try utf-8 first, fall back to latin-1, then give up gracefully."""
    raw_bytes = uploaded_file.read()

    for encoding in ["utf-8", "latin-1", "cp1252"]:
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), encoding=encoding)
            if df.empty or len(df.columns) == 0:
                return ParseResult(False, error="The CSV appears to be empty or has no readable columns.")
            warning = None
            if encoding != "utf-8":
                warning = f"File wasn't standard UTF-8 — read using {encoding} encoding instead."
            return ParseResult(True, df=df, warning=warning)
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            return ParseResult(False, error="This CSV file is empty.")
        except pd.errors.ParserError as e:
            return ParseResult(False, error=f"Couldn't parse this CSV — it may have inconsistent columns per row. ({str(e)[:150]})")
        except Exception as e:
            return ParseResult(False, error=f"Unexpected error reading CSV: {str(e)[:150]}")

    return ParseResult(False, error="Couldn't decode this file with common encodings (UTF-8, Latin-1, CP1252). Try re-saving it as UTF-8 CSV.")


def get_excel_sheet_names(uploaded_file):
    """Returns list of sheet names, or None on failure."""
    try:
        xls = pd.ExcelFile(uploaded_file)
        return xls.sheet_names
    except Exception:
        return None


def parse_excel(uploaded_file, sheet_name=None):
    """Parse a specific sheet, or the first sheet if none specified."""
    try:
        if sheet_name is None:
            df = pd.read_excel(uploaded_file, sheet_name=0)
        else:
            df = pd.read_excel(uploaded_file, sheet_name=sheet_name)

        if df.empty or len(df.columns) == 0:
            return ParseResult(False, error="This sheet appears to be empty or has no readable columns.")

        return ParseResult(True, df=df)
    except Exception as e:
        return ParseResult(False, error=f"Couldn't read this Excel file/sheet: {str(e)[:150]}")


def clean_and_validate(df):
    """
    Light cleanup pass: drop fully-empty rows/columns, warn about heavy nulls.
    Returns (cleaned_df, warnings_list)
    """
    warnings = []
    original_shape = df.shape

    df = df.dropna(how="all")  # drop fully empty rows
    df = df.dropna(axis=1, how="all")  # drop fully empty columns

    if df.shape != original_shape:
        warnings.append(
            f"Removed fully empty rows/columns — went from {original_shape[0]}x{original_shape[1]} "
            f"to {df.shape[0]}x{df.shape[1]}."
        )

    # Warn (don't block) on columns that are mostly null
    for col in df.columns:
        null_pct = df[col].isna().mean()
        if null_pct > 0.5:
            warnings.append(f"Column '{col}' is {round(null_pct*100)}% empty — results involving it may be unreliable.")

    return df, warnings


def get_schema_description(df, max_sample_values=3):
    """
    Builds a compact schema description to send to the LLM.
    This is what makes the LLM's formulas/SQL/Python actually correct
    instead of guessed.
    """
    lines = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        samples = df[col].dropna().unique()[:max_sample_values]
        samples_str = ", ".join(str(s) for s in samples)
        lines.append(f"- {col} ({dtype}): e.g. {samples_str}")
    return "\n".join(lines)
