# Noise to Insights

Turns a survey export into findings you can act on.

"Pricing came up a lot" is an observation. **"Pricing came up three times more
often among trial users than paid users, and that gap is unlikely to be noise"**
is a finding. This tool does the second part.

Upload a CSV or Excel export of survey responses. Open-ended answers are grouped
by similarity, each group is named as a theme, and every theme is cross-tabulated
against your respondent segments and tested for significance.

## Why it clusters before it asks a model

Sending a thousand raw responses to an LLM and asking for themes produces a
plausible-sounding summary that nobody can audit. Here the responses are
clustered with TF-IDF and k-means **first**, so every theme is a real, countable
set of responses you can open and read. The model's job is only to *name* a group
it is shown — it never decides which responses belong together, and it never sees
the whole dataset at once.

Below 25 responses that inverts: TF-IDF over a few dozen short answers carries
too little signal for k-means to split meaningfully, so the model reads every
response and assigns themes itself.

## Why the statistics are conservative

Crosstabbing a dozen themes against six segments runs dozens of chi-square tests.
At an uncorrected p < 0.05 that manufactures findings. Two guards:

- **Benjamini–Hochberg correction** across all comparisons in a run — only
  results that survive it are labelled significant.
- **A minimum expected cell count of 5.** Below that the app reports the counts
  and says the test isn't valid, rather than printing a bogus p-value. With a
  dozen themes and two segment levels this needs roughly 120+ responses before a
  comparison becomes testable at all, and a few hundred in practice.

Effect size (Cramér's V) is reported alongside every p-value, because with
several hundred responses a tiny difference will clear significance while meaning
nothing.

## Column profiling

You never tell it which question was open-ended. Each column is classified as:

| Kind | Rule | Used as |
|---|---|---|
| `text` | long values (avg ≥ 25 chars), mostly distinct (≥ 55% unique) | the answers to theme |
| `categorical` | ≤ 30 distinct values, or a numeric column with ≤ 10 levels | a segment to compare across |
| `numeric` | numeric with more than 10 distinct values | reported, not tested |
| `identifier` | near-unique short values | ignored — emails, ticket numbers |

A numeric rating scale is deliberately treated as categorical: a 1–5 satisfaction
score is more useful as a segment than as a distribution.

## Running it

Two processes. The backend's CORS policy allows exactly the origin in
`FRONTEND_URL`, so use `localhost` (not `127.0.0.1`) in the browser.

**Backend** — Python 3.12, run from `backend/`:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY
.venv/bin/uvicorn main:app --port 8000 --reload
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev                   # http://localhost:5173
```

Interactive API docs at http://localhost:8000/docs.

## Configuration

All of it lives in `backend/.env` (see `.env.example`):

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(none)* | Required for theming. Without it, upload and profiling still work |
| `MODEL` | `claude-opus-5` | |
| `FRONTEND_URL` | `http://localhost:5173` | The single allowed CORS origin |
| `DATA_DIR` | `backend/data` | Uploads + DuckDB. Delete it to reset |
| `MIN_RESPONSES_FOR_CLUSTERING` | `25` | Below this, responses are themed directly |

`GET /api/health` reports `llm_configured`, so you can tell a missing key from a
broken one before starting a run.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/datasets` | Upload an export; returns the id and column profile |
| `GET` | `/api/datasets` | List uploaded datasets |
| `GET` | `/api/datasets/{id}` | Profile plus the saved analysis, if any |
| `GET` | `/api/datasets/{id}/responses?column=` | Raw answers, to read a theme back to source |
| `DELETE` | `/api/datasets/{id}` | Drop the table and the stored upload |
| `GET` | `/api/analysis/{id}/stream` | **SSE.** Progress events, then the result |
| `GET` | `/api/health` | Status and whether an API key is configured |

The analysis endpoint streams rather than blocking: a run does real work
(clustering, one model call per group, a chi-square per segment), and the stream
names the stage currently running. Frames are `progress`, `narrative`, `result`
and `error`. The result is persisted as it is emitted, so a refresh after a
disconnect still finds it.

Handlers are deliberately sync (`def`). DuckDB is blocking and guarded by a
single lock, so FastAPI's threadpool is what that design expects — an `async def`
handler would run those blocking calls on the event loop.

## Architecture

```
frontend/            Vite + React, no chart library (bars and the heatmap are plain CSS)
backend/
  main.py            app, CORS, health
  routers/           datasets.py (CRUD)  analysis.py (SSE)
  modules/
    ingest.py        encoding sniffing, banner-row promotion, dedup
    profiling.py     column classification
    clustering.py    TF-IDF + k-means, k chosen by silhouette score
    llm.py           every model call in the app lives here
    statistics.py    chi-square, Cramér's V, Benjamini–Hochberg
    analysis.py      the run, as a generator of progress events
  utils/
    store.py         DuckDB persistence
    config.py        settings, read once at import
```

Swapping model providers means rewriting `modules/llm.py` and nothing else —
nothing above that layer knows what produced a theme.

## Tests

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Ten tests, about ten seconds, no API key and no network. Everything except
`modules/llm.py` runs for real; the three model calls are replaced with
deterministic stand-ins.

The substantive ones generate a synthetic export in which `Plan` predicts the
theme and `Region` is assigned at random, then assert that the pipeline finds the
first and rejects the second — a test that fails if either the clustering or the
correction stops working. Others cover the under-powered case (a reason, never a
p-value), the small-survey path that skips clustering, upload rejection,
persistence, and the 404/400 boundaries.

## Status

Verified on 2026-09-07:

- The test suite above passes: ingest, profiling, clustering, chi-square, FDR,
  SSE streaming, persistence and delete all work end to end. The planted effect
  is detected (p = 1.7e-71, Cramér's V = 0.71); the random one is not.
- The browser path was exercised for real — a headless Chrome `EventSource`
  driving `streamAnalysis()` received five named `progress` frames and a
  terminating `error` frame, with CORS headers correct on the streaming
  response.
- Frontend builds under strict TypeScript; results render correctly in light and
  dark.

**Not verified: the live model calls.** There is no `ANTHROPIC_API_KEY` on this
machine, so `llm.name_clusters`, `llm.theme_directly` and `llm.narrative_stream`
have never run against the real API — they were stubbed for the tests above. Set
a key and run once before trusting the theming path.

Also outstanding:

- **Google Sheets ingestion is not implemented.** `config.py` still carries
  `GOOGLE_CREDENTIALS_PATH` and `REDIRECT_URI`, and `requirements.txt` still
  pulls the `google-auth` stack, for a `modules/sheets.py` that was never
  written. Either build it or drop the dependencies.
- **Profiling edge case.** A long free-text column with many repeated answers
  (unique ratio below 0.55, more than 30 distinct values) falls through to
  `identifier` and won't be offered for theming. Real open text is near-unique so
  this rarely bites, but the thresholds in `config.py` are the dial if it does.
