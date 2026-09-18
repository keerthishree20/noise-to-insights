"""Noise to Insights -- FastAPI entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import analysis, datasets
from utils.config import FRONTEND_URL, GEMINI_MODEL, LLM_PROVIDER, MODEL, ensure_dirs

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    if LLM_PROVIDER is None:
        # Uploading and profiling work without a key; theming does not. Say so
        # at boot rather than letting the first analysis fail mysteriously.
        log.warning(
            "No ANTHROPIC_API_KEY or GEMINI_API_KEY set -- uploads and profiling "
            "will work, but any analysis will stop at the theming step. Copy "
            ".env.example to .env and add a key."
        )
    yield


app = FastAPI(
    title="Noise to Insights",
    description="Turns open-ended survey responses into themes you can act on.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets.router)
app.include_router(analysis.router)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, object]:
    """Whether the app can actually complete an analysis, not just respond."""
    return {
        "status": "ok",
        "llm_configured": LLM_PROVIDER is not None,
        "provider": LLM_PROVIDER,
        "model": GEMINI_MODEL if LLM_PROVIDER == "gemini" else MODEL,
    }
