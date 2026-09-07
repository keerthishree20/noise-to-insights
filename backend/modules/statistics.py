"""Test whether a theme lands differently across respondent segments.

"Pricing came up a lot" is an observation. "Pricing came up three times more
often among trial users than paid users, and that gap is unlikely to be noise"
is a finding. This module does the second part.
"""

from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

from utils.config import MIN_EXPECTED_CELL_COUNT

# Benjamini-Hochberg target. Crosstabbing every theme against every segment
# runs dozens of tests, so an uncorrected p < 0.05 would manufacture findings.
FDR_ALPHA = 0.05


def _cramers_v(chi2: float, table: np.ndarray) -> float:
    """Effect size for a chi-square test, on a 0-1 scale."""
    n = table.sum()
    if n == 0:
        return 0.0
    smaller_dim = min(table.shape) - 1
    if smaller_dim < 1:
        return 0.0
    return float(np.sqrt(chi2 / (n * smaller_dim)))


def theme_by_segment(
    frame: pd.DataFrame,
    theme_assignments: dict[int, str],
    segment_column: str,
) -> dict[str, Any]:
    """Cross-tabulate themes against one segment column and test independence.

    `theme_assignments` maps a DataFrame row index to a theme label. Rows that
    were not themed (blank answers) are excluded rather than bucketed, so the
    percentages describe people who actually answered.
    """
    rows = [i for i in theme_assignments if i in frame.index]
    if not rows:
        return {"segment": segment_column, "testable": False, "reason": "no themed rows"}

    paired = pd.DataFrame(
        {
            "theme": [theme_assignments[i] for i in rows],
            "segment": frame.loc[rows, segment_column].astype(str).str.strip(),
        }
    )
    paired = paired[paired["segment"].notna() & (paired["segment"] != "") & (paired["segment"].str.lower() != "nan")]

    if paired.empty:
        return {"segment": segment_column, "testable": False, "reason": "segment is empty"}

    table = pd.crosstab(paired["theme"], paired["segment"])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return {
            "segment": segment_column,
            "testable": False,
            "reason": "needs at least two themes and two segment values",
            "counts": table.to_dict(),
        }

    chi2, p_value, _, expected = chi2_contingency(table.values)

    # Chi-square assumes reasonably populated cells. Below that, report the
    # counts and say the test isn't valid rather than print a bogus p-value.
    min_expected = float(expected.min())
    if min_expected < MIN_EXPECTED_CELL_COUNT:
        return {
            "segment": segment_column,
            "testable": False,
            "reason": (
                f"too few responses per cell for a valid test "
                f"(smallest expected count {min_expected:.1f}, needs {MIN_EXPECTED_CELL_COUNT:.0f})"
            ),
            "counts": table.to_dict(),
            "percentages": _column_percentages(table),
        }

    return {
        "segment": segment_column,
        "testable": True,
        "p_value": float(p_value),
        "chi2": float(chi2),
        "cramers_v": _cramers_v(float(chi2), table.values),
        "counts": table.to_dict(),
        "percentages": _column_percentages(table),
        "n": int(table.values.sum()),
    }


def _column_percentages(table: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Share of each segment that fell into each theme (columns sum to 100)."""
    totals = table.sum(axis=0).replace(0, np.nan)
    pct = (table / totals * 100).round(1).fillna(0.0)
    return pct.to_dict()


def apply_fdr(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark which testable results survive Benjamini-Hochberg correction."""
    testable = [r for r in results if r.get("testable")]
    if not testable:
        return results

    ordered = sorted(testable, key=lambda r: r["p_value"])
    m = len(ordered)
    threshold_index = -1
    for i, result in enumerate(ordered, start=1):
        if result["p_value"] <= (i / m) * FDR_ALPHA:
            threshold_index = i

    for i, result in enumerate(ordered, start=1):
        result["significant"] = i <= threshold_index
        result["fdr_threshold"] = round((i / m) * FDR_ALPHA, 5)

    return results
