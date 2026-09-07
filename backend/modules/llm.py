"""Every Claude call in the app lives here.

Keeping the provider behind one module means swapping to a different LLM is a
rewrite of this file and nothing else. Nothing above this layer knows what
model produced a theme.
"""

import logging

import anthropic
from pydantic import BaseModel, Field

from utils.config import ANTHROPIC_API_KEY, MODEL

log = logging.getLogger(__name__)

# How many exemplar responses per cluster Claude sees when naming a theme.
# The cluster may hold hundreds; the closest few to the centroid are enough to
# name it, and keep the request small.
EXEMPLARS_PER_CLUSTER = 8
# Cap on responses sent when there are too few to cluster.
MAX_DIRECT_RESPONSES = 120


class LLMUnavailable(RuntimeError):
    """Raised when no API key is configured, or Claude declined the request."""


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

    response = _client().messages.parse(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=ThemeSet,
    )
    _check_refusal(response)

    themes = response.parsed_output.themes
    # Claude occasionally returns fewer themes than groups; pad so the caller
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
        valid = [i for i in theme.response_indices if 0 <= i < len(capped) and i not in seen]
        seen.update(valid)
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

    with _client().messages.stream(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            yield chunk
        _check_refusal(stream.get_final_message())
