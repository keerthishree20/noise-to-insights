"""Run an analysis and stream its progress to the browser over SSE.

The route is a GET because the browser's `EventSource` only issues GETs. The
analysis itself is `modules.analysis.run_analysis`, a sync generator doing
blocking pandas/sklearn/HTTP work; `EventSourceResponse` iterates a sync
iterator in a threadpool, so the event loop stays free while it runs.
"""

import json
import logging
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from modules import llm
from modules.analysis import run_analysis
from utils import store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/{dataset_id}/stream")
def stream_analysis(
    dataset_id: str,
    text_column: str | None = None,
    segments: list[str] | None = Query(default=None),
) -> EventSourceResponse:
    """Stream progress events, then the finished result.

    Both `text_column` and `segments` fall back to what profiling nominated at
    upload time, so the client can start a run with no arguments at all.
    """
    dataset = store.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(404, "No dataset with that id.")

    profile = dataset.get("profile") or {}
    column = text_column or profile.get("suggested_text_column")
    if not column:
        raise HTTPException(
            400,
            "This dataset has no free-text column to analyse. Open-ended answers "
            "are what this tool themes.",
        )

    chosen_segments = segments if segments is not None else profile.get("segment_columns", [])

    # Loading the frame here, outside the generator, means a missing table
    # surfaces as a clean 404 rather than an error event mid-stream.
    frame = store.load_frame(dataset_id)
    if column not in frame.columns:
        raise HTTPException(404, f"No column named {column!r} in this dataset.")

    return EventSourceResponse(_events(dataset_id, frame, column, list(chosen_segments)))


def _events(dataset_id: str, frame, column: str, segments: list[str]) -> Iterator[dict[str, str]]:
    """Adapt `run_analysis` events to SSE frames, and persist the result."""
    try:
        for event in run_analysis(frame, column, segments):
            if event.get("type") == "result":
                # Persist before forwarding, so a client that disconnects on the
                # last frame still finds the result waiting on reload.
                store.save_result(dataset_id, event["result"])
            yield _frame(event)

    except llm.LLMUnavailable as exc:
        # The common case: no API key. That is a configuration problem, not a
        # crash, and the message explains how to fix it.
        yield _frame({"type": "error", "message": str(exc)})

    except Exception as exc:  # noqa: BLE001 - the stream must end with an event
        log.exception("analysis failed for %s", dataset_id)
        yield _frame({"type": "error", "message": f"Analysis failed: {exc}"})


def _frame(event: dict[str, Any]) -> dict[str, str]:
    return {"event": event.get("type", "message"), "data": json.dumps(event)}
