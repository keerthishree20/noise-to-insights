"""Upload, list, inspect and delete datasets.

Handlers here are deliberately sync (`def`, not `async def`). DuckDB access in
`utils/store.py` is blocking and guarded by a lock, so FastAPI running these in
its threadpool is what that design expects -- an `async def` handler would run
the same blocking calls on the event loop and stall every other request.
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from modules.ingest import IngestError, load_table
from modules.profiling import profile_frame
from utils import store
from utils.config import UPLOAD_DIR, ensure_dirs

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

# Refuse oversized uploads before pandas tries to parse them into memory.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("")
def upload_dataset(file: UploadFile = File(...)) -> dict[str, Any]:
    """Parse an uploaded export, profile its columns, and store it."""
    # `file.file` is the underlying spooled file, readable from a sync handler.
    raw = file.file.read()

    if not raw:
        raise HTTPException(400, "That file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"That file is {len(raw) / 1_048_576:.1f} MB. The limit is "
            f"{MAX_UPLOAD_BYTES // 1_048_576} MB.",
        )

    name = file.filename or "upload.csv"

    try:
        frame = load_table(raw, name)
    except IngestError as exc:
        # IngestError messages are written for the person who uploaded the file.
        raise HTTPException(400, str(exc)) from exc

    profile = profile_frame(frame)
    dataset_id = store.new_dataset_id()
    store.save_dataset(dataset_id, name, frame, profile)

    # Keep the original file. The parsed table is in DuckDB, but the raw export
    # is what you go back to when a parse looks wrong.
    ensure_dirs()
    suffix = Path(name).suffix[:10]
    (UPLOAD_DIR / f"{dataset_id}{suffix}").write_bytes(raw)

    return {
        "id": dataset_id,
        "name": name,
        "row_count": len(frame),
        "profile": profile,
    }


@router.get("")
def list_datasets() -> list[dict[str, Any]]:
    return store.list_datasets()


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str) -> dict[str, Any]:
    dataset = _require(dataset_id)
    return dataset


@router.get("/{dataset_id}/responses")
def get_responses(dataset_id: str, column: str, limit: int = 200) -> dict[str, Any]:
    """The raw answers behind a theme, so a finding can be read back to source."""
    _require(dataset_id)
    frame = store.load_frame(dataset_id)

    if column not in frame.columns:
        raise HTTPException(404, f"No column named {column!r} in this dataset.")

    series = frame[column].dropna()
    values = [str(v) for v in series.head(max(1, min(limit, 1000)))]
    return {"column": column, "total": int(len(series)), "responses": values}


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str) -> None:
    _require(dataset_id)
    store.delete_dataset(dataset_id)
    for path in UPLOAD_DIR.glob(f"{dataset_id}*"):
        path.unlink(missing_ok=True)


def _require(dataset_id: str) -> dict[str, Any]:
    """Fetch a dataset or 404. Also rejects ids that aren't safe as table names."""
    try:
        store.table_name(dataset_id)
    except ValueError as exc:
        raise HTTPException(400, "That is not a valid dataset id.") from exc

    dataset = store.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(404, "No dataset with that id.")
    return dataset
