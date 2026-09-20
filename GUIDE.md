# Noise to Insights — Complete Project Guide

A complete guide from zero to a working survey analysis tool. Covers every feature, every design
decision and the reason behind it, with the real code. It is self-contained: you can paste it into
any AI chat and ask questions about the project without sharing the repository.

**Repository:** https://github.com/keerthishree20/noise-to-insights
**All projects:** https://github.com/keerthishree20

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack & Why](#2-tech-stack--why)
3. [Project Setup from Scratch](#3-project-setup-from-scratch)
4. [Core Ideas in Plain Words](#4-core-ideas-in-plain-words)
5. [Project Structure](#5-project-structure)
6. [Uploading a Survey (Ingest)](#6-uploading-a-survey-ingest)
7. [Column Profiling](#7-column-profiling)
8. [Clustering Before the Model](#8-clustering-before-the-model)
9. [Naming Themes with an AI Model](#9-naming-themes-with-an-ai-model)
10. [Small Surveys: Direct Theming](#10-small-surveys-direct-theming)
11. [Two Model Providers: Claude and Gemini](#11-two-model-providers-claude-and-gemini)
12. [Segment Comparison: Chi-Square](#12-segment-comparison-chi-square)
13. [Effect Size: Cramér's V](#13-effect-size-cramérs-v)
14. [Multiple Testing: Benjamini-Hochberg](#14-multiple-testing-benjamini-hochberg)
15. [The Written Readout](#15-the-written-readout)
16. [The Analysis Run and Live Progress (SSE)](#16-the-analysis-run-and-live-progress-sse)
17. [Storage with DuckDB](#17-storage-with-duckdb)
18. [Frontend](#18-frontend)
19. [API Reference](#19-api-reference)
20. [Configuration](#20-configuration)
21. [Testing](#21-testing)
22. [What Is and Is Not Verified](#22-what-is-and-is-not-verified)
23. [Troubleshooting](#23-troubleshooting)
24. [Complete Feature Summary](#24-complete-feature-summary)

---

## 1. Project Overview

Noise to Insights turns a **survey export** into findings you can act on.

"Pricing came up a lot" is an observation. **"Pricing came up three times more often among trial users
than paid users, and that gap is unlikely to be noise"** is a finding. This tool does the second part.

You upload a CSV or Excel file of survey responses. The app:
1. works out which column holds the open-ended answers and which columns are segments,
2. groups similar answers into themes,
3. asks an AI model to **name** each theme,
4. tests whether each theme appears more in some segments than others, with a correction for running
   many tests at once,
5. writes a short plain-language readout, streamed live.

**Status:** runnable end to end, 18 tests pass. Verified live with Gemini on 2026-09-18. Not deployed.

---

## 2. Tech Stack & Why

| Technology | Role | Why We Chose It |
|---|---|---|
| **FastAPI** | Backend | typed routes, automatic docs, Server-Sent Events via `sse-starlette` |
| **pandas** | Data | reading exports and cross-tabulating |
| **scikit-learn** | Clustering | TF-IDF, k-means, silhouette score |
| **scipy** | Statistics | `chi2_contingency` |
| **DuckDB** | Storage | a fast embedded analytical database in one file |
| **chardet, openpyxl** | Ingest | encoding detection, Excel files |
| **Anthropic Claude or Google Gemini** | Naming themes, readout | one module; Gemini is the free option |
| **Vite + React + TypeScript** | Frontend | light, fast; no chart library needed |

---

## 3. Project Setup from Scratch

### Backend (Python 3.12; the system `python3` is 3.6)
```bash
git clone https://github.com/keerthishree20/noise-to-insights.git
cd noise-to-insights/backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY, or GEMINI_API_KEY for the free option
.venv/bin/uvicorn main:app --port 8000 --reload
```
API docs: http://localhost:8000/docs

### Frontend
```bash
cd ../frontend
npm install
cp .env.example .env.local
npm run dev                   # http://localhost:5173
```

Open **http://localhost:5173**, not `127.0.0.1:5173`: the backend allows exactly one CORS origin.

Without any model key, upload and profiling still work; the analysis stops at the theming step.

---

## 4. Core Ideas in Plain Words

| Idea | Meaning |
|---|---|
| **Open-ended answer** | free text like "the price is too high for what we get" |
| **Segment** | a group column like plan (Trial/Paid), region, or a 1–5 rating |
| **TF-IDF** | turns text into numbers, weighting words that are distinctive in a response |
| **k-means** | groups similar vectors into k clusters |
| **Silhouette score** | how well separated clusters are; used to pick k |
| **Chi-square test** | could the theme-by-segment pattern be chance? |
| **p-value** | the chance of seeing a pattern this strong if there were no real difference |
| **Cramér's V** | how big the difference is, 0 to 1 |
| **False discovery rate** | with many tests, some "significant" results are luck; the correction limits that |

---

## 5. Project Structure

```
backend/
  main.py              app, CORS, health
  routers/
    datasets.py        upload, list, get, responses, delete
    analysis.py        GET /api/analysis/{id}/stream (Server-Sent Events)
  modules/
    ingest.py          encoding detection, banner-row promotion, duplicate headers
    profiling.py       column kinds, suggested text column and segments
    clustering.py      TF-IDF + k-means, k chosen by silhouette
    llm.py             every model call: Claude or Gemini
    statistics.py      chi-square, Cramér's V, Benjamini-Hochberg
    analysis.py        run_analysis(): the pipeline as a generator of events
  utils/
    store.py           DuckDB persistence
    config.py          settings, provider choice, thresholds
  tests/
    test_pipeline.py      the pipeline with the model stubbed
    test_llm_gemini.py    the Gemini path with HTTP stubbed
frontend/src/
  App.tsx  main.tsx  types.ts  index.css
  pages/Home.tsx  pages/DatasetView.tsx
  components/UploadDropzone.tsx  AnalysisSetup.tsx  ProgressLog.tsx
             Results.tsx  ThemeBars.tsx  SegmentCrosstab.tsx
  api/client.ts
```

---

## 6. Uploading a Survey (Ingest)

`modules/ingest.py` `load_table(raw, filename)` accepts `.csv`, `.tsv`, `.txt`, `.xlsx`, `.xlsm`, `.xls`.

### Encoding detection
```python
def detect_encoding(raw):
    guess = chardet.detect(raw[:MAX_SNIFF_BYTES])
    encoding = (guess.get("encoding") or "utf-8").lower()
    confidence = guess.get("confidence") or 0.0
    if confidence < 0.7 or encoding in {"ascii", "utf-8"}:
        return "utf-8"          # chardet says "ascii" on short files; UTF-8 is always safe
    return encoding
```
CSV reading tries the guessed encoding, then UTF-8, then Latin-1, and sniffs the separator.

### Banner rows
Some tools put a title above the real header. If pandas produced mostly `Unnamed: N` columns and the
first data row is fully filled, that row is promoted to be the header.

### Duplicate headers
Repeated column names are renamed so every column is unique.

---

## 7. Column Profiling

You never say which question was open-ended. `modules/profiling.py` classifies every column:

```python
if numeric:
    return "categorical" if unique <= 10 else "numeric"   # a 1–5 rating is a segment
if avg_chars >= 25 and unique_ratio >= 0.55:
    return "text"                                          # the answers to theme
if unique_ratio > 0.95 and avg_chars < 25:
    return "identifier"                                    # emails, ticket numbers
if unique values <= 30:
    return "categorical"                                   # a segment
return "identifier"
```

| Kind | Used as |
|---|---|
| `text` | the answers to theme |
| `categorical` | a segment to compare across |
| `numeric` | reported, not tested |
| `identifier` | ignored |

`profile_frame()` also suggests the text column and the segment columns, which the setup screen
pre-selects.

---

## 8. Clustering Before the Model

### Why cluster first?
Sending a thousand raw responses to an AI model and asking for themes gives a plausible-sounding
summary that nobody can check. Here, responses are clustered with **TF-IDF and k-means first**, so every
theme is a real, countable set of responses you can open and read. The model only **names** a group it
is shown; it never decides which responses belong together, and never sees the whole dataset.

```python
TfidfVectorizer(stop_words="english", ngram_range=(1, 2),
                min_df=2 if n_docs >= 50 else 1,        # drop one-off words only when there are enough docs
                max_df=0.85 if n_docs >= 20 else 1.0,
                sublinear_tf=True, strip_accents="unicode")

def _choose_k(matrix, n_docs):
    upper = min(MAX_CLUSTERS, max(MIN_CLUSTERS, n_docs // TARGET_CLUSTER_SIZE))
    for k in range(MIN_CLUSTERS, upper + 1):             # 2 to 12
        labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(matrix)
        score = silhouette_score(matrix, labels, metric="cosine")
        keep the best
```

Each `Cluster` has its size, row indices, distinctive keywords, and the **exemplars** closest to its
centre.

---

## 9. Naming Themes with an AI Model

`llm.name_clusters(clusters, question)` sends, per group: its size, distinctive terms, and up to 8
representative responses. The model returns exactly one theme per group:

```python
class Theme(BaseModel):
    label: str       # a short noun phrase, 2-5 words
    summary: str     # one sentence
    sentiment: str   # positive, negative, mixed, neutral
```

The system prompt tells it to use the respondents' own words, never marketing language, never invent a
theme, and never soften criticism. If the model returns fewer themes than groups, the rest are padded
as "Group N" so nothing breaks.

---

## 10. Small Surveys: Direct Theming

Below **25** responses (`MIN_RESPONSES_FOR_CLUSTERING`), TF-IDF over a few short answers carries too
little signal for k-means. So `llm.theme_directly(texts)` lets the model read every response (up to 120)
and assign each one to 2–6 themes by index.

The reply is cleaned: indices out of range are dropped, a response assigned to two themes stays in the
first, **a response listed twice inside one theme is counted once** (a bug fixed on 2026-09-18), and any
leftover responses go into "Other".

---

## 11. Two Model Providers: Claude and Gemini

Every model call lives in `modules/llm.py`, so nothing else knows which model produced a theme.

```python
def _pick_provider():
    chosen = os.getenv("LLM_PROVIDER", "").strip().lower()
    if chosen in ("anthropic", "gemini"):
        return chosen
    if ANTHROPIC_API_KEY:
        return "anthropic"
    if GEMINI_API_KEY:
        return "gemini"
    return None
```

| Provider | Model | Cost |
|---|---|---|
| Anthropic Claude | `MODEL`, default `claude-opus-5` | paid |
| Google Gemini | `GEMINI_MODEL`, default `gemini-2.5-flash` | free tier |

### How the Gemini path works
- Calls Gemini's REST API with `httpx` (installed with the Anthropic library, so no new dependency).
- **Structured output:** `responseMimeType: application/json` plus the Pydantic model's JSON schema,
  then validated with Pydantic.
- **Retries** on 429, 500 and 503 (overloaded free tier), waiting 2, 4 and 8 seconds.
- A **404** means the model was retired, and the error says to change `GEMINI_MODEL`.
- A blocked prompt or safety stop becomes a clear "declined" error.
- The readout streams through `streamGenerateContent?alt=sse`.

The Claude path uses `messages.parse` with the Pydantic models and checks for refusals.

---

## 12. Segment Comparison: Chi-Square

`statistics.theme_by_segment(frame, theme_assignments, segment_column)`:

```python
table = pd.crosstab(paired["theme"], paired["segment"])
if table.shape[0] < 2 or table.shape[1] < 2:
    return {"testable": False, "reason": "needs at least two themes and two segment values", ...}
chi2, p_value, _, expected = chi2_contingency(table.values)
if expected.min() < 5:
    return {"testable": False,
            "reason": "too few responses per cell for a valid test (smallest expected count ...)",
            "counts": ..., "percentages": ...}
return {"testable": True, "p_value": ..., "chi2": ..., "cramers_v": ..., "counts": ..., "percentages": ...}
```

### Why refuse small cells?
Chi-square is invalid when any expected count is under 5. Printing a p-value there would be a lie, so
the app shows the counts and says why. With a dozen themes and two segment values, you need roughly 120+
responses before a comparison is testable at all, and a few hundred in practice.

Blank answers are excluded, so percentages describe people who actually answered.

---

## 13. Effect Size: Cramér's V

A p-value says "unlikely to be chance". It does not say "big". With several hundred responses, a tiny
difference can be significant and still meaningless. So **Cramér's V** (0 = no association, 1 = total)
is shown with every p-value.

---

## 14. Multiple Testing: Benjamini-Hochberg

Crosstabbing many themes against several segments runs many tests. At p < 0.05, some will pass by luck.

```python
def apply_fdr(results):
    ordered = sorted(testable, key=lambda r: r["p_value"])
    m = len(ordered)
    for i, result in enumerate(ordered, start=1):
        if result["p_value"] <= (i / m) * FDR_ALPHA:
            threshold_index = i
    for i, result in enumerate(ordered, start=1):
        result["significant"] = i <= threshold_index
```

Only results that survive this correction are labelled **significant**.

---

## 15. The Written Readout

`llm.narrative_stream(summary_payload)` streams three short paragraphs "for someone who will act on
them": lead with what matters most, mention a segment difference **only if it is marked significant**, no
headings or bullets.

The payload is compact JSON of themes and test results: **no raw responses and no row ids** are sent.

---

## 16. The Analysis Run and Live Progress (SSE)

`modules/analysis.py` `run_analysis(frame, text_column, segments)` is a **generator** that yields events
as it works:

| Stage | Example message |
|---|---|
| reading | "Found 80 substantive responses" |
| clustering | "Found 6 distinct groups" |
| theming | "Asking the model to name each group" |
| stats | "Comparing themes across 2 segments" |
| narrative | the readout, chunk by chunk |
| result | the full result |

`routers/analysis.py` sends them as **Server-Sent Events** with frame types `progress`, `narrative`,
`result` and `error`.

### Why GET?
The browser's `EventSource` only sends GET requests.

### Why sync handlers?
Route handlers are plain `def`, not `async def`. DuckDB calls block and share one lock, and FastAPI
runs `def` handlers in a thread pool. `async def` would block the event loop.

**The result is saved as it is sent**, so a refresh after a disconnect still finds it.

---

## 17. Storage with DuckDB

`utils/store.py` keeps everything in `DATA_DIR` (`backend/data`):
- a `datasets` table: id, name, profile, saved result,
- **one table per upload** holding the rows,
- the original uploaded files.

Functions: `save_dataset`, `load_frame`, `get_dataset`, `list_datasets`, `save_result`,
`delete_dataset`. Delete the folder to reset everything.

---

## 18. Frontend

Vite, React, TypeScript, **no chart library**: bars and the heatmap are plain CSS.

| File | Purpose |
|---|---|
| `App.tsx` | the shell and the list of past datasets |
| `pages/Home.tsx` | the upload screen |
| `pages/DatasetView.tsx` | one dataset: profile, setup, live progress, results |
| `UploadDropzone` | drag-and-drop upload |
| `AnalysisSetup` | choose the text column and segments |
| `ProgressLog` | the live stage log and the streaming readout |
| `ThemeBars` | each theme's share of responses |
| `SegmentCrosstab` | theme-by-segment heatmap with p-values, V and significance |
| `Results` | the full readout |
| `api/client.ts` | fetch calls and `streamAnalysis()` with `EventSource` |

It renders correctly in light and dark.

---

## 19. API Reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/datasets` | upload; returns id and column profile |
| GET | `/api/datasets` | list uploads |
| GET | `/api/datasets/{id}` | profile plus saved analysis |
| GET | `/api/datasets/{id}/responses?column=` | raw answers, to read a theme back to its source |
| DELETE | `/api/datasets/{id}` | drop the data and the stored upload |
| GET | `/api/analysis/{id}/stream?text_column=&segments=` | SSE progress then the result |
| GET | `/api/health` | status, `llm_configured`, `provider`, `model` |

---

## 20. Configuration

`backend/.env`:

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Claude, paid |
| `GEMINI_API_KEY` | none | Gemini, free tier; used when there is no Anthropic key |
| `LLM_PROVIDER` | automatic | force `anthropic` or `gemini` |
| `MODEL` | `claude-opus-5` | Claude model |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model |
| `FRONTEND_URL` | `http://localhost:5173` | the single allowed CORS origin |
| `DATA_DIR` | `backend/data` | uploads and DuckDB |
| `MIN_RESPONSES_FOR_CLUSTERING` | 25 | below this, themed directly |

Profiling thresholds (`TEXT_MIN_AVG_CHARS = 25`, `TEXT_MIN_UNIQUE_RATIO = 0.55`,
`MIN_EXPECTED_CELL_COUNT = 5`) are in `utils/config.py`.

---

## 21. Testing

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 18 tests, about 10 seconds, no key, no network
```

- **`test_pipeline.py` (10):** builds a synthetic export where `Plan` really predicts the theme and
  `Region` is random, and asserts the pipeline finds the first and rejects the second. It fails if
  clustering or the correction breaks. Also: the under-powered case, the small-survey path, upload
  rejection, persistence, 404/400 responses.
- **`test_llm_gemini.py` (8):** the Gemini path with HTTP stubbed: structured output, padding, retries,
  a retired model, a blocked prompt, a malformed reply, index clean-up, and no key at all.

The planted-effect test detected the effect at p = 1.7e-71, Cramér's V = 0.71; the random segment was
correctly not significant.

---

## 22. What Is and Is Not Verified

- **Verified:** the full pipeline with stubbed model calls; SSE streaming from a real headless browser
  with correct CORS; frontend build in light and dark.
- **Verified 2026-09-18 with Gemini:** a live 80-response analysis named six groups sensibly ("Support
  reply time", "Cost for small team"...) and streamed a readout.
- **Not verified:** the Claude path, because no Anthropic key was available.
- **Dropped:** Google Sheets import (export as CSV or XLSX instead).
- **Known edge case:** a long free-text column with many repeated answers (unique ratio below 0.55) is
  classified as an identifier and not offered for theming; the thresholds in `config.py` are the dial.
- **Not deployed.**

---

## 23. Troubleshooting

| Problem | Fix |
|---|---|
| every request fails in the browser | you opened `127.0.0.1:5173`; use `localhost:5173` |
| theming fails but upload works | `/api/health` shows `llm_configured`; add a key and restart |
| "model is overloaded" | wait a minute and run again; Gemini's free tier has spikes |
| my question is not offered for theming | answers repeat too often; adjust thresholds in `config.py` |
| every comparison says "not valid" | too few responses per cell; fewer segments or more responses |
| start over | stop the backend and delete `backend/data` |

---

## 24. Complete Feature Summary

### All Features Built

| # | Feature | Type | Key Files |
|---|---|---|---|
| 1 | CSV and Excel ingest with encoding detection | Backend | `ingest.py` |
| 2 | Banner-row promotion, duplicate headers | Backend | `ingest.py` |
| 3 | Automatic column profiling | Backend | `profiling.py` |
| 4 | TF-IDF + k-means with silhouette k | Analysis | `clustering.py` |
| 5 | AI theme naming from exemplars | AI | `llm.py` |
| 6 | Direct theming for small surveys | AI | `llm.py` |
| 7 | Claude and Gemini providers | AI | `llm.py`, `config.py` |
| 8 | Chi-square with validity check | Statistics | `statistics.py` |
| 9 | Cramér's V effect size | Statistics | `statistics.py` |
| 10 | Benjamini-Hochberg correction | Statistics | `statistics.py` |
| 11 | Streamed written readout | AI | `llm.py`, `analysis.py` |
| 12 | Live progress over SSE | Backend | `routers/analysis.py` |
| 13 | DuckDB persistence | Backend | `store.py` |
| 14 | Theme bars and crosstab heatmap | Frontend | `ThemeBars.tsx`, `SegmentCrosstab.tsx` |
| 15 | Stubbed pipeline and provider tests | Testing | `tests/` |

### Data Flow Architecture

```
Browser (Vite + React, :5173)
  └── upload ──► POST /api/datasets
        └── load_table (encoding, banner row, dedupe) ──► profile_frame ──► DuckDB
  └── Analyse ──► GET /api/analysis/{id}/stream  (EventSource)
        └── run_analysis():
              reading ──► extract_responses(text column)
              ≥ 25 answers: cluster_responses (TF-IDF, k-means, silhouette) ──► llm.name_clusters
              < 25 answers: llm.theme_directly
              stats: theme_by_segment (chi-square, V, validity) per segment ──► apply_fdr
              narrative: llm.narrative_stream (compact JSON, no raw answers)
              result ──► saved to DuckDB and sent
        └── ProgressLog · ThemeBars · SegmentCrosstab · Results

llm.py ──► Anthropic (messages.parse / stream)  or  Gemini (REST, JSON schema, retries, SSE)
```

### Tech Stack at a Glance

```
Backend:   FastAPI, pandas, scikit-learn, scipy, DuckDB, sse-starlette, chardet, openpyxl
AI:        Anthropic Claude (paid) or Google Gemini (free tier), one module
Frontend:  Vite + React + TypeScript, plain CSS charts
Testing:   pytest with a planted-effect synthetic survey and stubbed providers
```
