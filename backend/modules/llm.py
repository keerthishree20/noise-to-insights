"""Every model call in the app lives here.

Keeping the provider behind one module means swapping to a different LLM is a
change to this file and nothing else. Nothing above this layer knows what
model produced a theme.

Two providers: Anthropic's Claude, and Google's Gemini as a free alternative.
`utils.config.LLM_PROVIDER` picks one from the keys that are set.
"""

import json
import logging
import time

import anthropic
import httpx
from pydantic import BaseModel, Field, ValidationError

from utils.config import ANTHROPIC_API_KEY, GEMINI_API_KEY, GEMINI_MODEL, LLM_PROVIDER, MODEL

log = logging.getLogger(__name__)

# How many exemplar responses per cluster Claude sees when naming a theme.
# The cluster may hold hundreds; the closest few to the centroid are enough to
# name it, and keep the request small.
EXEMPLARS_PER_CLUSTER = 8
# Cap on responses sent when there are too few to cluster.
MAX_DIRECT_RESPONSES = 120


class LLMUnavailable(RuntimeError):
    """Raised when no API key is configured, or the model declined the request."""


class Theme(BaseModel):
    label: str = Field(description="A short noun phrase naming the theme, 2-5 words")
    summary: str = Field(description="One sentence describing what respondents said")
    sentiment: str = Field(description="One of: positive, negative, mixed, neutral")


class ThemeSet(BaseModel):
    themes: list[Theme]


class DirectTheme(BaseModel):
    label: str = Field(description="A short noun phrase naming the theme, 2-5 words")
    summary: str = Field(description="One sentence describing what respondents said")
    sentiment: str = Field(description="One of: positive, negative, mixed, neutral")
    response_indices: list[int] = Field(
        description="Indices of the responses belonging to this theme, from the numbered list"
    )


class DirectThemeSet(BaseModel):
    themes: list[DirectTheme]


def _client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise LLMUnavailable(
            "No ANTHROPIC_API_KEY set. Copy .env.example to .env and add a key."
        )
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _require_provider() -> str:
    if LLM_PROVIDER is None:
        raise LLMUnavailable(
            "No model key set. Add ANTHROPIC_API_KEY, or GEMINI_API_KEY for the free "
            "Gemini option, to backend/.env."
        )
    return LLM_PROVIDER


# ---- Gemini ------------------------------------------------------------------

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:{method}"


def _gemini_body(prompt: str, max_tokens: int, schema: type[BaseModel] | None = None) -> dict:
    config: dict = {"maxOutputTokens": max_tokens}
    if schema is not None:
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = schema.model_json_schema()
    return {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": config,
    }


def _gemini_text(reply: dict) -> str:
    """The text of a Gemini reply, or LLMUnavailable if it was blocked or empty."""
    blocked = (reply.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        raise LLMUnavailable(f"Gemini declined to process this content ({blocked}).")
    candidates = reply.get("candidates") or []
    if not candidates:
        raise LLMUnavailable("Gemini returned no answer.")
    if candidates[0].get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
        raise LLMUnavailable(f"Gemini declined to process this content ({candidates[0]['finishReason']}).")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


GEMINI_RETRIES = 4


def _gemini_post(method: str, body: dict):
    """POST to Gemini, retrying the temporary overload errors free tiers see often."""
    if not GEMINI_API_KEY:
        raise LLMUnavailable("No GEMINI_API_KEY set. Add one to backend/.env from https://aistudio.google.com/apikey")
    url = GEMINI_URL.format(model=GEMINI_MODEL, method=method)
    for attempt in range(GEMINI_RETRIES):
        resp = httpx.post(url, json=body, headers={"x-goog-api-key": GEMINI_API_KEY}, timeout=120)
        if resp.status_code not in (429, 500, 503) or attempt == GEMINI_RETRIES - 1:
            return resp
        wait = 2 ** (attempt + 1)
        log.warning("Gemini returned %s, retrying in %ss", resp.status_code, wait)
        time.sleep(wait)
    return resp


def _gemini_parse(prompt: str, schema: type[BaseModel], max_tokens: int):
    """One structured call: Gemini is held to the Pydantic model's JSON schema."""
    try:
        resp = _gemini_post("generateContent", _gemini_body(prompt, max_tokens, schema))
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"Could not reach Gemini: {exc}") from exc
    if resp.status_code == 404:
        raise LLMUnavailable(
            f"Gemini has no model named {GEMINI_MODEL!r}; it was most likely retired. "
            "Set GEMINI_MODEL in backend/.env to a current one."
        )
    if resp.status_code >= 300:
        raise LLMUnavailable(f"Gemini returned {resp.status_code}: {resp.text[:300]}")
    text = _gemini_text(resp.json())
    try:
        return schema.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMUnavailable("Gemini's reply did not match the expected structure.") from exc


def _gemini_stream(prompt: str, max_tokens: int):
    """Yield text as Gemini produces it, over its server-sent events endpoint."""
    if not GEMINI_API_KEY:
        raise LLMUnavailable("No GEMINI_API_KEY set.")
    url = GEMINI_URL.format(model=GEMINI_MODEL, method="streamGenerateContent") + "?alt=sse"
    try:
        with httpx.stream("POST", url, json=_gemini_body(prompt, max_tokens),
                          headers={"x-goog-api-key": GEMINI_API_KEY}, timeout=120) as resp:
            if resp.status_code >= 300:
                resp.read()
                raise LLMUnavailable(f"Gemini returned {resp.status_code}: {resp.text[:300]}")
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    chunk = _gemini_text(json.loads(line[5:]))
                    if chunk:
                        yield chunk
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"Could not reach Gemini: {exc}") from exc


def _check_refusal(response) -> None:
    if getattr(response, "stop_reason", None) == "refusal":
        detail = getattr(response, "stop_details", None)
        category = getattr(detail, "category", None) if detail else None
        raise LLMUnavailable(f"Claude declined to process this content ({category}).")


SYSTEM = (
    "You analyse open-ended survey and feedback responses. You name themes using "
    "the respondents' own vocabulary, never marketing language. You never invent a "
    "theme that the responses do not support, and you never soften criticism."
)


def name_clusters(clusters: list, question: str | None = None) -> list[Theme]:
    """Name each pre-computed cluster. Returns one Theme per cluster, in order."""
    if not clusters:
        return []

    blocks = []
    for i, cluster in enumerate(clusters):
        quotes = "\n".join(
            f"  - {q}" for q in cluster.exemplars[:EXEMPLARS_PER_CLUSTER]
        )
        keywords = ", ".join(cluster.keywords) or "(none)"
        blocks.append(
            f"Group {i + 1} ({cluster.size} responses)\n"
            f"Distinctive terms: {keywords}\n"
            f"Representative responses:\n{quotes}"
        )

    asked = f"The survey question was: {question!r}\n\n" if question else ""
    prompt = (
        f"{asked}Responses have been grouped by textual similarity. Name each group "
        f"as a theme.\n\nReturn exactly {len(clusters)} themes, in the same order as "
        f"the groups below.\n\n" + "\n\n".join(blocks)
    )

    if _require_provider() == "gemini":
        themes = _gemini_parse(prompt, ThemeSet, 8000).themes
    else:
        response = _client().messages.parse(
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=ThemeSet,
        )
        _check_refusal(response)
        themes = response.parsed_output.themes

    # The model occasionally returns fewer themes than groups; pad so the caller
    # can zip themes against clusters without an index error.
    while len(themes) < len(clusters):
        idx = len(themes)
        themes.append(
            Theme(
                label=f"Group {idx + 1}",
                summary="No summary was returned for this group.",
                sentiment="neutral",
            )
        )
    return themes[: len(clusters)]


def theme_directly(texts: list[str], question: str | None = None) -> list[DirectTheme]:
    """Theme a small set of responses without clustering.

    Used below the clustering threshold, where TF-IDF has too little to work
    with. Claude reads every response and assigns it to a theme itself.
    """
    if not texts:
        return []

    capped = texts[:MAX_DIRECT_RESPONSES]
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(capped))
    asked = f"The survey question was: {question!r}\n\n" if question else ""

    prompt = (
        f"{asked}Group these {len(capped)} responses into themes. Aim for 2-6 themes; "
        f"use fewer if the responses genuinely say the same thing. Every response "
        f"index must appear in exactly one theme.\n\n{numbered}"
    )

    if _require_provider() == "gemini":
        themes = _gemini_parse(prompt, DirectThemeSet, 8000).themes
    else:
        response = _client().messages.parse(
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=DirectThemeSet,
        )
        _check_refusal(response)
        themes = response.parsed_output.themes

    # Drop hallucinated indices and any response assigned to two themes.
    seen: set[int] = set()
    cleaned: list[DirectTheme] = []
    for theme in themes:
        # Checked one at a time, so an index repeated inside the same theme is
        # also dropped; otherwise that response would be counted twice.
        valid = []
        for i in theme.response_indices:
            if 0 <= i < len(capped) and i not in seen:
                valid.append(i)
                seen.add(i)
        if valid:
            theme.response_indices = valid
            cleaned.append(theme)

    unassigned = [i for i in range(len(capped)) if i not in seen]
    if unassigned:
        cleaned.append(
            DirectTheme(
                label="Other",
                summary="Responses that did not fit the themes above.",
                sentiment="neutral",
                response_indices=unassigned,
            )
        )
    return cleaned


def narrative_stream(summary_payload: str):
    """Stream a plain-language readout of the finished analysis.

    Yields text chunks. The caller forwards them to the browser over SSE.
    """
    prompt = (
        "Write a short readout of these survey findings for someone who will act "
        "on them. Lead with what matters most. Mention a segment difference only "
        "if it is marked significant. Do not use headings or bullet points; three "
        "short paragraphs at most.\n\n" + summary_payload
    )

    if _require_provider() == "gemini":
        yield from _gemini_stream(prompt, 2000)
        return

    with _client().messages.stream(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            yield chunk
        _check_refusal(stream.get_final_message())
