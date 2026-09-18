"""The Gemini path in modules/llm.py, with the HTTP calls replaced. No network."""

import json

import pytest

from modules import llm


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def reply(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}, "finishReason": "STOP"}]}


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = []

    def install(*responses):
        queue = list(responses)

        def fake_post(url, json, headers, timeout):
            calls.append({"url": url, "json": json, "headers": headers})
            return queue.pop(0)

        monkeypatch.setattr(llm.httpx, "post", fake_post)
        return calls

    return install


class Cluster:
    def __init__(self, exemplars, size):
        self.exemplars, self.size, self.keywords = exemplars, size, ["price"]


def test_clusters_are_named_through_gemini_with_a_json_schema(gemini):
    calls = gemini(FakeResponse(200, reply({"themes": [
        {"label": "Price too high", "summary": "People say it costs too much.", "sentiment": "negative"}]})))
    themes = llm.name_clusters([Cluster(["too expensive"], 12)])
    assert [t.label for t in themes] == ["Price too high"]
    config = calls[0]["json"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert "themes" in json.dumps(config["responseJsonSchema"])
    assert calls[0]["headers"]["x-goog-api-key"] == "test-key"


def test_fewer_themes_than_groups_are_padded(gemini):
    gemini(FakeResponse(200, reply({"themes": []})))
    themes = llm.name_clusters([Cluster(["a"], 1), Cluster(["b"], 1)])
    assert [t.label for t in themes] == ["Group 1", "Group 2"]


def test_temporary_overload_is_retried(gemini):
    calls = gemini(FakeResponse(503, text="high demand"), FakeResponse(429, text="rate"),
                   FakeResponse(200, reply({"themes": [{"label": "A", "summary": "s", "sentiment": "neutral"}]})))
    assert llm.name_clusters([Cluster(["x"], 1)])[0].label == "A"
    assert len(calls) == 3


def test_a_retired_model_says_so(gemini):
    gemini(FakeResponse(404, text="not found"))
    with pytest.raises(llm.LLMUnavailable, match="retired"):
        llm.name_clusters([Cluster(["x"], 1)])


def test_a_blocked_prompt_is_reported(gemini):
    gemini(FakeResponse(200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(llm.LLMUnavailable, match="declined"):
        llm.name_clusters([Cluster(["x"], 1)])


def test_a_malformed_reply_is_reported(gemini):
    gemini(FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}))
    with pytest.raises(llm.LLMUnavailable, match="structure"):
        llm.name_clusters([Cluster(["x"], 1)])


def test_direct_theming_drops_bad_indices_and_collects_the_rest(gemini):
    gemini(FakeResponse(200, reply({"themes": [
        {"label": "Price", "summary": "s", "sentiment": "negative", "response_indices": [0, 0, 9]}]})))
    themes = llm.theme_directly(["too pricey", "slow support"])
    assert themes[0].response_indices == [0]
    assert themes[-1].label == "Other" and themes[-1].response_indices == [1]


def test_no_key_at_all_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", None)
    with pytest.raises(llm.LLMUnavailable, match="GEMINI_API_KEY"):
        llm.name_clusters([Cluster(["x"], 1)])
