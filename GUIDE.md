# Noise to Insights — Complete Project Guide

## Table of Contents
1. [What is Noise to Insights?](#what-is-noise-to-insights)
2. [Quick Start](#quick-start)
3. [Core Concepts](#core-concepts)
4. [Architecture](#architecture)
5. [The Analysis Pipeline](#the-analysis-pipeline)
6. [Backend Deep Dive](#backend-deep-dive)
7. [Frontend Deep Dive](#frontend-deep-dive)
8. [API Reference](#api-reference)
9. [Configuration](#configuration)
10. [Testing Strategy](#testing-strategy)
11. [What Is and Is Not Verified](#what-is-and-is-not-verified)
12. [Troubleshooting](#troubleshooting)

---

## What is Noise to Insights?

A tool that turns a survey export into findings you can act on.

You upload a CSV or Excel file of survey responses. The app:
1. works out which column holds the open-ended answers and which columns are segments,
2. groups similar answers into themes,
3. asks a language model to name each theme,
4. tests whether each theme appears more in some segments than others, with a correction for
   running many tests at once,
5. writes a short readout.

The difference it aims for: "pricing came up a lot" is an observation. "Pricing came up three times
more often among trial users than paid users, and that gap is unlikely to be noise" is a finding.

The model is Anthropic's Claude, set by `MODEL`, which defaults to `claude-opus-5`. Running it costs
money.

---

## Quick Start

The system `python3` here is 3.6, so use Python 3.12.

### Backend
```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY
.venv/bin/uvicorn main:app --port 8000 --reload
```
Interactive API docs are at http://localhost:8000/docs.

### Frontend
```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev                   # http://localhost:5173
```

Open **http://localhost:5173**, not `127.0.0.1:5173`. The backend allows exactly one CORS origin.

Without an API key, upload and column profiling still work. Theming does not.

---

## Core Concepts

### Column profiling
You never say which question was open-ended. Each column is classified:

| kind | rule | used as |
|---|---|---|
| `text` | average length at least 25 characters, at least 55% unique | the answers to theme |
| `categorical` | at most 30 distinct values, or numeric with at most 10 levels | a segment |
| `numeric` | numeric with more than 10 distinct values | reported, not tested |
| `identifier` | near-unique short values such as emails | ignored |

A 1 to 5 rating is treated as categorical, because it is more useful as a segment.

### Cluster first, then name
Answers are grouped with TF-IDF and k-means **before** the model sees them. The model only names each
group it is shown. So every theme is a real, countable set of answers you can open and read. `k`,
the number of groups, is chosen by silhouette score between 2 and 12.

Below 25 answers, clustering has too little signal, so the model reads every answer and assigns
themes directly.

### Chi-square test
For each theme and segment, a table counts how often the theme appears in each segment group. The
chi-square test asks whether that pattern could be chance.

### Cramér's V
The effect size, from 0 for no association to 1 for complete. With hundreds of responses a tiny
difference can be "significant" and still meaningless, so V is always shown with the p-value.

### Benjamini-Hochberg correction
A dozen themes against six segments means dozens of tests. At p < 0.05 some will pass by luck. This
correction controls the share of false findings across the whole run. Only results that survive it
are labelled significant.

### Minimum expected count
Chi-square is invalid when any expected cell count is under 5. The app then reports the counts and
says why the test is not valid, instead of printing a meaningless p-value. In practice you need a few
hundred responses.

---

## Architecture

```
  Browser (Vite + React, :5173)
    UploadDropzone ─ POST /api/datasets
    AnalysisSetup  ─ GET  /api/analysis/{id}/stream   (Server-Sent Events)
    ProgressLog, Results, ThemeBars, SegmentCrosstab
              │
              ▼
  FastAPI (:8000)  main.py
    routers/datasets.py    upload, list, get, responses, delete
    routers/analysis.py    SSE stream of run_analysis()
              │
    modules/ingest.py      encoding sniffing, banner rows, duplicate headers
    modules/profiling.py   column kinds, suggested text column and segments
    modules/clustering.py  TF-IDF + k-means
    modules/llm.py         every model call in the app
    modules/statistics.py  chi-square, Cramér's V, Benjamini-Hochberg
    modules/analysis.py    the run, as a generator of progress events
              │
    utils/store.py         DuckDB in DATA_DIR: datasets table, one table per upload, saved results
```

Route handlers are plain `def`, not `async def`, on purpose. DuckDB calls block and share one lock,
and FastAPI runs `def` handlers in a threadpool. An `async def` handler would block the event loop.

Changing model provider means rewriting `modules/llm.py` only.

---

## The Analysis Pipeline

`modules/analysis.py` `run_analysis(frame, text_column, segments)` yields events as it goes:

1. **reading.** Extract substantive answers from the text column.
2. **clustering.** TF-IDF and k-means, or skipped below 25 answers.
3. **theming.** `llm.name_clusters()` names each group, or `llm.theme_directly()` for small surveys.
4. **stats.** `statistics.theme_by_segment()` for each segment, then `apply_fdr()` across all tests.
5. **narrative.** `llm.narrative_stream()` streams a written readout.
6. **result.** The full result, saved to DuckDB as it is sent, so a page refresh still finds it.

Each event becomes one SSE frame of type `progress`, `narrative`, `result` or `error`.

---

## Backend Deep Dive

| file | key functions |
|---|---|
| `modules/ingest.py` | `load_table()`, `detect_encoding()`, `_drop_banner_row()` for exports with a title row, `_dedupe()` for repeated headers |
| `modules/profiling.py` | `profile_frame()` classifies columns and suggests the text column and segments. `extract_responses()` |
| `modules/clustering.py` | `cluster_responses()` returns `Cluster`s. `_choose_k()` by silhouette |
| `modules/llm.py` | `name_clusters()`, `theme_directly()`, `narrative_stream()`, and a refusal check |
| `modules/statistics.py` | `theme_by_segment()`, `_cramers_v()`, `apply_fdr()` |
| `modules/analysis.py` | `run_analysis()` and segment ranking |
| `utils/store.py` | `save_dataset()`, `load_frame()`, `get_dataset()`, `list_datasets()`, `save_result()`, `delete_dataset()` |
| `utils/config.py` | settings read once at import, including the profiling thresholds |

---

## Frontend Deep Dive

Vite and React with no chart library. Bars and the heatmap are plain CSS.

| file | purpose |
|---|---|
| `src/App.tsx` | the shell, and the list of past datasets |
| `src/pages/Home.tsx` | the upload screen |
| `src/pages/DatasetView.tsx` | one dataset: profile, setup, progress, results |
| `src/components/UploadDropzone.tsx` | drag-and-drop upload |
| `src/components/AnalysisSetup.tsx` | choose the text column and segments |
| `src/components/ProgressLog.tsx` | the live stage-by-stage log from the stream |
| `src/components/ThemeBars.tsx` | each theme's share of responses |
| `src/components/SegmentCrosstab.tsx` | the theme-by-segment heatmap with p-values and V |
| `src/components/Results.tsx` | assembles the readout |
| `src/api/client.ts` | fetch calls and `streamAnalysis()` with `EventSource` |

---

## API Reference

| method | path | purpose |
|---|---|---|
| `POST` | `/api/datasets` | upload an export. Returns its id and column profile |
| `GET` | `/api/datasets` | list uploads |
| `GET` | `/api/datasets/{id}` | profile plus saved analysis, if any |
| `GET` | `/api/datasets/{id}/responses?column=` | raw answers, to read a theme back to source |
| `DELETE` | `/api/datasets/{id}` | drop the data and the stored upload |
| `GET` | `/api/analysis/{id}/stream?text_column=&segments=` | SSE progress, then the result |
| `GET` | `/api/health` | status and `llm_configured` |

The stream is a `GET` because browsers' `EventSource` only sends GETs. `text_column` and `segments`
default to what profiling suggested.

---

## Configuration

`backend/.env`:

| variable | default | notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | required for theming |
| `MODEL` | `claude-opus-5` | |
| `FRONTEND_URL` | `http://localhost:5173` | the single allowed CORS origin |
| `DATA_DIR` | `backend/data` | uploads and DuckDB. Delete it to reset |
| `MIN_RESPONSES_FOR_CLUSTERING` | `25` | below this, the model themes directly |

---

## Testing Strategy

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Ten tests in `tests/test_pipeline.py`, no API key and no network. Everything runs for real except the
three model calls, which are replaced with deterministic stand-ins.

The key test builds a synthetic export where `Plan` really predicts the theme and `Region` is
random, then asserts the pipeline finds the first and rejects the second. If clustering or the
correction breaks, it fails. Other tests cover the under-powered case, the small-survey path,
upload rejection, persistence, and 400 and 404 responses.

---

## What Is and Is Not Verified

- **Verified:** the full pipeline with stubbed model calls, the SSE stream from a real browser with
  correct CORS headers, and the frontend build in light and dark.
- **Not verified:** the live model calls. No API key was available, so theming and the narrative
  have never run against the real API. Run once with a key before trusting them.
- **Dropped:** Google Sheets import. Export the sheet as CSV or XLSX instead.
- **Not deployed.**

---

## Troubleshooting

### Every request fails in the browser
You opened `127.0.0.1:5173`. Use `localhost:5173`, or change `FRONTEND_URL` to match.

### Theming fails but upload works
`GET /api/health` shows `llm_configured`. If it is false, add `ANTHROPIC_API_KEY` to `backend/.env`
and restart.

### My open-ended question is not offered for theming
Its answers repeat too often, so profiling classified it as an identifier. The thresholds are in
`utils/config.py`.

### Every comparison says the test is not valid
Too few responses per cell. Use fewer segments, segments with fewer levels, or more responses.

### Start over
Stop the backend and delete `backend/data`.
