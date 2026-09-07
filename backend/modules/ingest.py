"""Turn an uploaded CSV or Excel file into a clean DataFrame.

Survey exports are messy in predictable ways: they arrive in whatever encoding
the exporting tool felt like using, and the first row is sometimes a banner
rather than a header. Both are handled here so the rest of the app can assume
a well-formed frame.
"""

import io

import chardet
import pandas as pd

MAX_SNIFF_BYTES = 64_000


class IngestError(ValueError):
    """Raised when a file cannot be parsed into a usable table."""


def detect_encoding(raw: bytes) -> str:
    """Guess a text encoding, preferring UTF-8 when the guess is weak.

    chardet reports low confidence on short files and likes to answer
    'ascii', which breaks the moment a curly quote appears. UTF-8 is a strict
    superset of ASCII, so widening is always safe.
    """
    guess = chardet.detect(raw[:MAX_SNIFF_BYTES])
    encoding = (guess.get("encoding") or "utf-8").lower()
    confidence = guess.get("confidence") or 0.0
    if confidence < 0.7 or encoding in {"ascii", "utf-8"}:
        return "utf-8"
    return encoding


def _read_csv(raw: bytes) -> pd.DataFrame:
    encoding = detect_encoding(raw)
    for enc in (encoding, "utf-8", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc, sep=None, engine="python")
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise IngestError("Could not parse this file as CSV.")


def _read_excel(raw: bytes) -> pd.DataFrame:
    try:
        return pd.read_excel(io.BytesIO(raw), engine="openpyxl")
    except Exception as exc:  # openpyxl raises a wide range of errors
        raise IngestError(f"Could not parse this file as Excel: {exc}") from exc


def _drop_banner_row(frame: pd.DataFrame) -> pd.DataFrame:
    """Handle exports whose real header sits under a one-cell title row.

    Signature: pandas produced mostly 'Unnamed: N' columns, and the first data
    row is fully populated. That row is the true header.
    """
    unnamed = sum(str(c).startswith("Unnamed:") for c in frame.columns)
    if len(frame) < 2 or unnamed < max(2, len(frame.columns) // 2):
        return frame
    header = frame.iloc[0]
    if header.isna().any():
        return frame
    promoted = frame.iloc[1:].copy()
    promoted.columns = [str(v).strip() for v in header]
    return promoted.reset_index(drop=True)


def load_table(raw: bytes, filename: str) -> pd.DataFrame:
    """Parse an uploaded file into a DataFrame, or raise IngestError."""
    lowered = filename.lower()
    if lowered.endswith((".xlsx", ".xlsm", ".xls")):
        frame = _read_excel(raw)
    elif lowered.endswith((".csv", ".tsv", ".txt")):
        frame = _read_csv(raw)
    else:
        raise IngestError(
            "Unsupported file type. Upload a .csv, .tsv, .xlsx or .xls export."
        )

    frame = _drop_banner_row(frame)
    frame = frame.dropna(axis=0, how="all").dropna(axis=1, how="all")

    if frame.empty:
        raise IngestError("That file has no rows in it.")

    frame.columns = _dedupe([str(c).strip() for c in frame.columns])
    return frame.reset_index(drop=True)


def _dedupe(names: list[str]) -> list[str]:
    """Make column names unique and non-empty; DuckDB rejects duplicates."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, name in enumerate(names):
        base = name or f"column_{i + 1}"
        if base in seen:
            seen[base] += 1
            base = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
        out.append(base)
    return out
