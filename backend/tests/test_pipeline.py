"""End-to-end tests for the analysis pipeline, with the model calls stubbed.

Everything except `modules/llm.py` is exercised for real: ingest, profiling,
clustering, chi-square, Benjamini-Hochberg, the SSE route, and persistence.
The model calls are replaced with deterministic stand-ins so the suite runs
offline, costs nothing, and gives the same answer every time.

What this suite does NOT cover is the live API calls themselves -- see the
Status section of the README.
"""

import io
import json
import random

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from modules import llm

# --- synthetic survey --------------------------------------------------------

PRICING = [
    "the price went up {pct}% this year and I can't justify it for a team of {n}",
    "way too expensive for what you get, we are evaluating {alt} instead",
    "billing is confusing and the per-seat cost adds up fast at {n} seats",
    "cost is the main blocker, the annual plan is out of reach on our budget",
    "we were quoted {pct}% more at renewal with no new features to show for it",
]
SUPPORT = [
    "support took {n} days to answer a blocking issue in production",
    "the support team fixed my problem in under an hour, no complaints there",
    "nobody responded to ticket #{n} until I escalated it publicly",
    "helpdesk replies fast but the answers are copy-pasted and miss the point",
    "I have had {n} tickets open for weeks with no owner assigned",
]
ONBOARDING = [
    "setup took a whole afternoon because the docs skip step {n}",
    "getting started was painful, the import tool failed {n} times in a row",
    "onboarding docs are out of date compared to the actual UI as of {alt}",
    "it took {n} tries to connect our data source during initial setup",
    "the first-run walkthrough assumes you already have {alt} configured",
]
ALTS = ["a competitor", "the legacy tool", "a spreadsheet", "an internal script"]
TAILS = [
    "Otherwise the product does what we need.",
    "I have raised this with our account manager already.",
    "This is the one thing stopping us renewing.",
    "Everything else has been solid so far.",
    "It has been like this since we signed up.",
    "Not a dealbreaker but worth flagging.",
]


def _phrase(rng: random.Random, pool: list[str]) -> str:
    body = rng.choice(pool).format(
        pct=rng.randint(5, 60), n=rng.randint(2, 40), alt=rng.choice(ALTS)
    )
    # The trailing clause and reference number keep answers near-unique, the way
    # real free text is. A small pool of repeated strings profiles as
    # `categorical`, not `text` -- correctly, since that is a closed question.
    return f"{body}. {rng.choice(TAILS)} (ref {rng.randint(10000, 99999)})"


def survey_csv(rows: int, seed: int = 7) -> bytes:
    """A feedback export where `Plan` predicts the theme and `Region` does not."""
    rng = random.Random(seed)
    records = []
    for i in range(rows):
        if i % 3 == 0:
            plan, pool = "Trial", PRICING
        elif i % 3 == 1:
            plan, pool = "Paid", SUPPORT
        else:
            plan, pool = rng.choice(["Trial", "Paid"]), ONBOARDING
        records.append(
            {
                "Respondent ID": f"R{1000 + i}",
                "Plan": plan,
                "Region": rng.choice(["APAC", "EMEA", "Americas"]),
                "NPS": rng.randint(0, 10),
                "What could we do better?": _phrase(rng, pool),
            }
        )
    return pd.DataFrame(records).to_csv(index=False).encode("utf-8")


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient over a throwaway DuckDB, with the model calls stubbed."""
    # Point storage at a temp dir so a test run never touches the developer's
    # real database (and never fights the dev server for DuckDB's file lock).
    #
    # These have to be patched on the *importing* modules, not on utils.config:
    # both do `from utils.config import ...`, which binds the value into their
    # own namespace at import time, so rebinding it on config has no effect.
    from routers import datasets as datasets_router
    from utils import store

    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(store, "_conn", None)
    monkeypatch.setattr(datasets_router, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(datasets_router, "ensure_dirs", lambda: None)

    def fake_name_clusters(clusters, question=None):
        return [
            llm.Theme(
                label=" ".join(c.keywords[:2]).title() or f"Group {c.id}",
                summary=f"{c.size} responses.",
                sentiment="mixed",
            )
            for c in clusters
        ]

    def fake_theme_directly(texts, question=None):
        # Split on a word that only appears in the pricing responses, so the
        # assignment is deterministic and checkable.
        priced = [i for i, t in enumerate(texts) if "price" in t or "cost" in t]
        other = [i for i in range(len(texts)) if i not in priced]
        themes = []
        if priced:
            themes.append(
                llm.DirectTheme(
                    label="Pricing",
                    summary="Cost came up.",
                    sentiment="negative",
                    response_indices=priced,
                )
            )
        if other:
            themes.append(
                llm.DirectTheme(
                    label="Everything else",
                    summary="Other topics.",
                    sentiment="mixed",
                    response_indices=other,
                )
            )
        return themes

    def fake_narrative(payload):
        yield "Stubbed readout."

    monkeypatch.setattr(llm, "name_clusters", fake_name_clusters)
    monkeypatch.setattr(llm, "theme_directly", fake_theme_directly)
    monkeypatch.setattr(llm, "narrative_stream", fake_narrative)

    import main

    with TestClient(main.app) as c:
        yield c


def upload(client, csv: bytes, name: str = "feedback.csv"):
    response = client.post(
        "/api/datasets", files={"file": (name, io.BytesIO(csv), "text/csv")}
    )
    assert response.status_code == 200, response.text
    return response.json()


def run_analysis(client, dataset_id: str, **params):
    """Drive the SSE route and return (events, result)."""
    events = []
    with client.stream("GET", f"/api/analysis/{dataset_id}/stream", params=params) as s:
        assert s.status_code == 200
        assert "text/event-stream" in s.headers["content-type"]
        for line in s.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))

    result = next((e["result"] for e in events if e["type"] == "result"), None)
    return events, result


# --- profiling ---------------------------------------------------------------


def test_profiling_identifies_column_roles(client):
    profile = upload(client, survey_csv(300))["profile"]
    kinds = {c["name"]: c["kind"] for c in profile["columns"]}

    assert kinds["What could we do better?"] == "text"
    assert kinds["Respondent ID"] == "identifier"
    assert kinds["Plan"] == "categorical"
    # A 0-10 rating has more than ten levels, so it stays numeric.
    assert kinds["NPS"] == "numeric"

    assert profile["suggested_text_column"] == "What could we do better?"
    assert set(profile["segment_columns"]) == {"Plan", "Region"}
    assert "Respondent ID" not in profile["segment_columns"]


@pytest.mark.parametrize(
    "filename,payload,expected",
    [
        ("notes.pdf", b"%PDF-1.4 not a table", "Unsupported file type"),
        ("empty.csv", b"", "empty"),
    ],
)
def test_bad_uploads_are_rejected_with_a_readable_message(
    client, filename, payload, expected
):
    response = client.post(
        "/api/datasets", files={"file": (filename, io.BytesIO(payload), "text/csv")}
    )
    assert response.status_code in (400, 413)
    assert expected.lower() in response.json()["detail"].lower()


# --- the clustered path ------------------------------------------------------


def test_finds_a_real_segment_effect_and_rejects_a_random_one(client):
    """The planted Plan effect must be detected; random Region must not be."""
    dataset = upload(client, survey_csv(720))
    events, result = run_analysis(client, dataset["id"])

    assert result is not None, [e for e in events if e["type"] == "error"]
    assert result["clustered"] is True
    assert result["response_count"] == 720

    stages = [e["stage"] for e in events if e["type"] == "progress"]
    assert {"reading", "clustering", "theming", "stats"} <= set(stages)

    shares = sum(t["share"] for t in result["themes"])
    assert abs(shares - 100) < 1.5, f"theme shares sum to {shares}"

    by_segment = {s["segment"]: s for s in result["segments"]}

    plan = by_segment["Plan"]
    assert plan["testable"], plan.get("reason")
    assert plan["significant"], f"planted effect missed (p={plan['p_value']})"
    assert plan["cramers_v"] > 0.3, "planted effect should be a large effect"

    # Region was assigned at random, so calling it significant is a false positive.
    assert not by_segment["Region"].get("significant")


def test_underpowered_comparison_is_refused_rather_than_reported(client):
    """Too few responses per cell must yield a reason, never a p-value."""
    dataset = upload(client, survey_csv(120))
    _, result = run_analysis(client, dataset["id"])

    refused = [s for s in result["segments"] if not s["testable"]]
    assert refused, "a 120-row survey over ~12 themes should be underpowered"
    for segment in refused:
        assert "p_value" not in segment
        assert segment["reason"]


# --- the direct-theming path (below the clustering threshold) ----------------


def test_small_surveys_skip_clustering(client):
    """Under MIN_RESPONSES_FOR_CLUSTERING the model themes responses directly."""
    dataset = upload(client, survey_csv(15))
    events, result = run_analysis(client, dataset["id"])

    assert result is not None, [e for e in events if e["type"] == "error"]
    assert result["clustered"] is False
    assert result["themes"], "direct theming produced no themes"

    # Every response lands in exactly one theme.
    assigned = sum(t["size"] for t in result["themes"])
    assert assigned == result["response_count"]

    messages = " ".join(e["message"] for e in events if e["type"] == "progress")
    assert "directly" in messages
    assert not any(e.get("stage") == "clustering" for e in events)


# --- persistence and the rest of the surface ---------------------------------


def test_result_is_persisted_and_dataset_can_be_deleted(client):
    dataset = upload(client, survey_csv(300))
    dataset_id = dataset["id"]

    assert client.get(f"/api/datasets/{dataset_id}").json()["result"] is None
    assert client.get("/api/datasets").json()[0]["analyzed"] is False

    _, result = run_analysis(client, dataset_id)
    assert result is not None

    saved = client.get(f"/api/datasets/{dataset_id}").json()
    assert saved["result"]["themes"] == result["themes"]
    assert client.get("/api/datasets").json()[0]["analyzed"] is True

    assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204
    assert client.get(f"/api/datasets/{dataset_id}").status_code == 404


def test_responses_endpoint_reads_a_theme_back_to_source(client):
    dataset = upload(client, survey_csv(60))

    body = client.get(
        f"/api/datasets/{dataset['id']}/responses",
        params={"column": "What could we do better?", "limit": 5},
    ).json()

    assert body["total"] == 60
    assert len(body["responses"]) == 5

    missing = client.get(
        f"/api/datasets/{dataset['id']}/responses", params={"column": "Nope"}
    )
    assert missing.status_code == 404


def test_unknown_dataset_is_a_404_not_a_stream(client):
    assert client.get("/api/datasets/deadbeef1234").status_code == 404
    assert client.get("/api/analysis/deadbeef1234/stream").status_code == 404
    # An id that could not be a table name is rejected before it reaches DuckDB.
    assert client.get("/api/datasets/not-a-valid-id").status_code == 400


def test_health_reports_whether_theming_can_run(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "llm_configured" in body and "model" in body
