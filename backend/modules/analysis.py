"""Run a full analysis, reporting progress as it goes.

`run_analysis` is a generator: it yields progress events and finally the
result. The SSE route forwards those events to the browser, so a long run
shows real stages instead of a spinner.
"""

import json
import logging
from typing import Any, Iterator

import pandas as pd

from modules import clustering, llm, statistics
from modules.profiling import extract_responses
from utils.config import MIN_RESPONSES_FOR_CLUSTERING

log = logging.getLogger(__name__)

# Segment columns to test against, most-populated first. Testing every column
# on a wide export would run hundreds of chi-squares for no added insight.
MAX_SEGMENTS_TESTED = 6


def _event(stage: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"type": "progress", "stage": stage, "message": message, **extra}


def run_analysis(
    frame: pd.DataFrame,
    text_column: str,
    segment_columns: list[str],
) -> Iterator[dict[str, Any]]:
    """Yield progress events, then one final {"type": "result", ...} event."""

    yield _event("reading", f"Reading responses from {text_column!r}")
    texts, row_indices = extract_responses(frame, text_column)

    if not texts:
        yield {
            "type": "error",
            "message": f"No usable free-text answers in {text_column!r}.",
        }
        return

    yield _event("reading", f"Found {len(texts)} substantive responses", count=len(texts))

    # --- Themes -------------------------------------------------------------
    theme_assignments: dict[int, str] = {}
    themes: list[dict[str, Any]] = []

    if len(texts) < MIN_RESPONSES_FOR_CLUSTERING:
        yield _event(
            "theming",
            f"Only {len(texts)} responses -- theming them directly rather than clustering",
            clustered=False,
        )
        direct = llm.theme_directly(texts, question=text_column)
        for theme in direct:
            members = [row_indices[i] for i in theme.response_indices]
            for row in members:
                theme_assignments[row] = theme.label
            themes.append(
                {
                    "label": theme.label,
                    "summary": theme.summary,
                    "sentiment": theme.sentiment,
                    "size": len(members),
                    "share": round(len(members) / len(texts) * 100, 1),
                    "keywords": [],
                    "exemplars": [texts[i] for i in theme.response_indices[:5]],
                    "row_indices": members,
                }
            )
    else:
        yield _event("clustering", f"Grouping {len(texts)} responses by similarity")
        clusters = clustering.cluster_responses(texts, row_indices)
        yield _event(
            "clustering",
            f"Found {len(clusters)} distinct groups",
            clustered=True,
            groups=len(clusters),
        )

        yield _event("theming", "Asking the model to name each group")
        named = llm.name_clusters(clusters, question=text_column)

        for cluster, theme in zip(clusters, named):
            for row in cluster.row_indices:
                theme_assignments[row] = theme.label
            themes.append(
                {
                    "label": theme.label,
                    "summary": theme.summary,
                    "sentiment": theme.sentiment,
                    "size": cluster.size,
                    "share": round(cluster.size / len(texts) * 100, 1),
                    "keywords": cluster.keywords,
                    "exemplars": cluster.exemplars,
                    "row_indices": cluster.row_indices,
                }
            )

    themes.sort(key=lambda t: t["size"], reverse=True)
    yield _event("theming", f"Named {len(themes)} themes", themes=len(themes))

    # --- Segment tests ------------------------------------------------------
    segment_results: list[dict[str, Any]] = []
    if segment_columns:
        ranked = _rank_segments(frame, segment_columns)[:MAX_SEGMENTS_TESTED]
        yield _event("stats", f"Comparing themes across {len(ranked)} segments")
        for column in ranked:
            try:
                segment_results.append(
                    statistics.theme_by_segment(frame, theme_assignments, column)
                )
            except Exception as exc:  # a bad column shouldn't kill the run
                log.warning("segment test failed for %s: %s", column, exc)
                segment_results.append(
                    {"segment": column, "testable": False, "reason": str(exc)}
                )
        statistics.apply_fdr(segment_results)

    significant = [s for s in segment_results if s.get("significant")]
    if segment_results:
        yield _event(
            "stats",
            f"{len(significant)} of {len(segment_results)} segment comparisons were significant",
        )

    # --- Narrative ----------------------------------------------------------
    yield _event("narrative", "Writing the readout")
    narrative = ""
    try:
        for chunk in llm.narrative_stream(_summary_payload(themes, segment_results, len(texts))):
            narrative += chunk
            yield {"type": "narrative", "text": chunk}
    except llm.LLMUnavailable as exc:
        log.warning("narrative unavailable: %s", exc)
        narrative = ""

    yield {
        "type": "result",
        "result": {
            "text_column": text_column,
            "response_count": len(texts),
            "clustered": len(texts) >= MIN_RESPONSES_FOR_CLUSTERING,
            "themes": themes,
            "segments": segment_results,
            "narrative": narrative,
        },
    }


def _rank_segments(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    """Prefer segments that are well populated and have few levels."""

    def score(column: str) -> tuple[int, int]:
        series = frame[column].dropna()
        return (-len(series), series.nunique())

    return sorted((c for c in columns if c in frame.columns), key=score)


def _summary_payload(
    themes: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    total: int,
) -> str:
    """Compact JSON for the narrative prompt -- no raw responses, no row ids."""
    return json.dumps(
        {
            "total_responses": total,
            "themes": [
                {
                    "label": t["label"],
                    "share_percent": t["share"],
                    "count": t["size"],
                    "sentiment": t["sentiment"],
                    "summary": t["summary"],
                }
                for t in themes
            ],
            "segment_comparisons": [
                {
                    "segment": s["segment"],
                    "significant": s.get("significant", False),
                    "p_value": s.get("p_value"),
                    "effect_size": s.get("cramers_v"),
                    "percentages": s.get("percentages"),
                }
                for s in segments
                if s.get("testable")
            ],
        },
        indent=2,
    )
