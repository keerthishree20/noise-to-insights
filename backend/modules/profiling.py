"""Classify each column as free text, categorical, numeric or identifier.

This is what lets the app work on a survey export it has never seen: the user
does not have to tell us which question was open-ended. Free-text columns get
themed; categorical columns become the segments those themes are compared
across.
"""

from typing import Any, Literal

import pandas as pd

from utils.config import TEXT_MIN_AVG_CHARS, TEXT_MIN_UNIQUE_RATIO

ColumnKind = Literal["text", "categorical", "numeric", "identifier", "empty"]

# A categorical column with this many distinct values is closer to an id than
# to a segment -- crosstabbing against it produces one row per respondent.
MAX_CATEGORY_LEVELS = 30


def _series_kind(series: pd.Series) -> tuple[ColumnKind, dict[str, Any]]:
    non_null = series.dropna()
    stats: dict[str, Any] = {
        "non_null": int(len(non_null)),
        "unique": int(non_null.nunique()),
    }

    if non_null.empty:
        return "empty", stats

    if pd.api.types.is_numeric_dtype(series):
        stats.update(
            mean=float(non_null.mean()),
            min=float(non_null.min()),
            max=float(non_null.max()),
        )
        # A numeric column with a handful of levels is a rating scale, which is
        # more useful as a segment than as a distribution.
        if stats["unique"] <= 10:
            return "categorical", stats
        return "numeric", stats

    text = non_null.astype(str).str.strip()
    text = text[text != ""]
    if text.empty:
        return "empty", stats

    avg_chars = float(text.str.len().mean())
    unique_ratio = text.nunique() / len(text)
    stats.update(avg_chars=round(avg_chars, 1), unique_ratio=round(unique_ratio, 3))

    if avg_chars >= TEXT_MIN_AVG_CHARS and unique_ratio >= TEXT_MIN_UNIQUE_RATIO:
        return "text", stats

    # Near-unique short strings are emails, ticket numbers, respondent ids.
    if unique_ratio > 0.95 and avg_chars < TEXT_MIN_AVG_CHARS:
        return "identifier", stats

    if text.nunique() <= MAX_CATEGORY_LEVELS:
        stats["levels"] = [str(v) for v in text.value_counts().head(MAX_CATEGORY_LEVELS).index]
        return "categorical", stats

    return "identifier", stats


def profile_frame(frame: pd.DataFrame) -> dict[str, Any]:
    """Describe every column, and nominate defaults for the analysis."""
    columns = []
    for name in frame.columns:
        kind, stats = _series_kind(frame[name])
        columns.append({"name": str(name), "kind": kind, **stats})

    text_columns = [c["name"] for c in columns if c["kind"] == "text"]
    segment_columns = [c["name"] for c in columns if c["kind"] == "categorical"]

    # Default to the open-text column with the most substantial answers -- on a
    # typical survey that is the "anything else?" question worth reading.
    by_length = sorted(
        (c for c in columns if c["kind"] == "text"),
        key=lambda c: c.get("avg_chars", 0),
        reverse=True,
    )

    return {
        "columns": columns,
        "text_columns": text_columns,
        "segment_columns": segment_columns,
        "suggested_text_column": by_length[0]["name"] if by_length else None,
    }


def extract_responses(
    frame: pd.DataFrame, column: str, min_chars: int = 3
) -> tuple[list[str], list[int]]:
    """Return the usable answers in `column` and their original row indices.

    Row indices are kept so a theme can be traced back to the respondent, and
    so segment crosstabs line up with the rows that were actually clustered.
    """
    if column not in frame.columns:
        raise KeyError(f"column {column!r} is not in this dataset")

    series = frame[column]
    texts: list[str] = []
    rows: list[int] = []
    for idx, value in series.items():
        if pd.isna(value):
            continue
        text = str(value).strip()
        # Filter the placeholder answers people type to skip a required field.
        if len(text) < min_chars or text.lower() in _NON_ANSWERS:
            continue
        texts.append(text)
        rows.append(int(idx))
    return texts, rows


_NON_ANSWERS = {
    "n/a", "na", "none", "nil", "no", "nope", "nothing", "-", "--", ".",
    "no comment", "no comments", "not applicable", "n.a.", "x", "?",
}
