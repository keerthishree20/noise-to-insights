"""DuckDB persistence.

One database file holds every dataset. Each uploaded file becomes a table
named `ds_<dataset_id>` plus a row in the `datasets` catalogue; analysis
results are written back as JSON so a page refresh doesn't re-run Claude.
"""

import json
import threading
import uuid
from typing import Any

import duckdb
import pandas as pd

from utils.config import DB_PATH, ensure_dirs

# DuckDB connections are not thread-safe and FastAPI runs sync handlers in a
# threadpool, so every statement goes through one lock-guarded connection.
_lock = threading.Lock()
_conn: duckdb.DuckDBPyConnection | None = None


def _connect() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        ensure_dirs()
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = duckdb.connect(str(DB_PATH))
        _init_schema(_conn)
    return _conn


def _init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS datasets (
            id           VARCHAR PRIMARY KEY,
            name         VARCHAR NOT NULL,
            row_count    INTEGER NOT NULL,
            created_at   TIMESTAMP DEFAULT current_timestamp,
            profile_json VARCHAR,
            result_json  VARCHAR
        )
        """
    )


def new_dataset_id() -> str:
    # Table names are interpolated, so keep the id strictly hex.
    return uuid.uuid4().hex[:12]


def table_name(dataset_id: str) -> str:
    if not dataset_id.isalnum():
        raise ValueError(f"unsafe dataset id: {dataset_id!r}")
    return f"ds_{dataset_id}"


def save_dataset(dataset_id: str, name: str, frame: pd.DataFrame, profile: dict[str, Any]) -> None:
    table = table_name(dataset_id)
    with _lock:
        conn = _connect()
        # `frame` is resolved by DuckDB's replacement scan on the local name.
        conn.register("incoming", frame)
        conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM incoming")
        conn.unregister("incoming")
        conn.execute(
            """
            INSERT INTO datasets (id, name, row_count, profile_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name,
                row_count = excluded.row_count,
                profile_json = excluded.profile_json
            """,
            [dataset_id, name, len(frame), json.dumps(profile)],
        )


def load_frame(dataset_id: str) -> pd.DataFrame:
    table = table_name(dataset_id)
    with _lock:
        return _connect().execute(f"SELECT * FROM {table}").fetch_df()


def get_dataset(dataset_id: str) -> dict[str, Any] | None:
    with _lock:
        row = (
            _connect()
            .execute(
                "SELECT id, name, row_count, created_at, profile_json, result_json "
                "FROM datasets WHERE id = ?",
                [dataset_id],
            )
            .fetchone()
        )
    if row is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "row_count": row[2],
        "created_at": row[3].isoformat() if row[3] else None,
        "profile": json.loads(row[4]) if row[4] else None,
        "result": json.loads(row[5]) if row[5] else None,
    }


def list_datasets() -> list[dict[str, Any]]:
    with _lock:
        rows = (
            _connect()
            .execute(
                "SELECT id, name, row_count, created_at, result_json IS NOT NULL "
                "FROM datasets ORDER BY created_at DESC"
            )
            .fetchall()
        )
    return [
        {
            "id": r[0],
            "name": r[1],
            "row_count": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "analyzed": bool(r[4]),
        }
        for r in rows
    ]


def save_result(dataset_id: str, result: dict[str, Any]) -> None:
    with _lock:
        _connect().execute(
            "UPDATE datasets SET result_json = ? WHERE id = ?",
            [json.dumps(result), dataset_id],
        )


def delete_dataset(dataset_id: str) -> None:
    table = table_name(dataset_id)
    with _lock:
        conn = _connect()
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DELETE FROM datasets WHERE id = ?", [dataset_id])
