"""Settings, read once from the environment at import time."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BACKEND_DIR / ".env")

# Where uploaded files and the DuckDB database live. Both are disposable --
# deleting the directory resets the app to a clean slate.
DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "insights.duckdb"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Claude is only ever called from modules/llm.py. Swapping providers means
# rewriting that one file, not hunting calls through the codebase.
MODEL = os.getenv("MODEL", "claude-opus-5")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")

# Google Sheets ingestion is not wired up -- see modules/sheets.py.
GOOGLE_CREDENTIALS_PATH = Path(
    os.getenv("GOOGLE_CREDENTIALS_PATH", BACKEND_DIR / "credentials.json")
)

# Below this many open-text responses, clustering is skipped and Claude themes
# the responses directly. TF-IDF vectors over a few dozen short answers carry
# too little signal for k-means to split them meaningfully.
MIN_RESPONSES_FOR_CLUSTERING = int(os.getenv("MIN_RESPONSES_FOR_CLUSTERING", "25"))

# A column is treated as free text when its values are long and mostly distinct.
TEXT_MIN_AVG_CHARS = 25
TEXT_MIN_UNIQUE_RATIO = 0.55

# Chi-square needs a minimum expected count per cell to mean anything.
MIN_EXPECTED_CELL_COUNT = 5.0


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
