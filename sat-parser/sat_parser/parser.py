"""The one function the rest of the app calls: parse_idea().

Flow:  text -> LLM (if available) -> normalize -> SatSpec
       on any LLM failure: text -> keyword fallback -> normalize -> SatSpec
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from .fallback import keyword_parse
from .llm import llm_parse, make_client
from .schema import SatSpec, normalize

MAX_INPUT_CHARS = 2000  # keeps prompts tiny and cost predictable


@dataclass
class ParseResult:
    spec: SatSpec
    source: str                      # "llm" or "fallback"
    error: Optional[str] = None      # why the LLM path wasn't used, if it wasn't
    usage: dict = field(default_factory=dict)


def _merge_previous(raw: dict, previous: Optional[SatSpec]) -> dict:
    """For follow-up edits in the fallback path: keep earlier values the new text didn't mention."""
    if previous is None:
        return raw
    base = previous.model_dump(exclude={"assumed", "warnings", "off_topic"})
    # Don't carry over values that were only defaults last time; let them stay "assumed".
    for key in previous.assumed:
        base.pop(key, None)
    raw = {k: v for k, v in raw.items() if k != "off_topic"}  # an edit like "make it 12U" is on topic
    return {**base, **raw}


def parse_idea(
    text: str,
    previous: Optional[SatSpec] = None,
    client=None,
    use_llm: Optional[bool] = None,
) -> ParseResult:
    """Parse a satellite idea into a SatSpec.

    text      the user's message
    previous  the spec from the last turn, for edits like "make it 12U"
    client    an Anthropic client (tests pass a fake one); created on demand otherwise
    use_llm   force on/off; default is on when ANTHROPIC_API_KEY is set
    """
    if not text or not text.strip():
        raise ValueError("Describe your satellite idea first.")
    text = text.strip()[:MAX_INPUT_CHARS]

    if use_llm is None:
        use_llm = client is not None or bool(os.environ.get("ANTHROPIC_API_KEY"))

    error = None
    if use_llm:
        try:
            client = client or make_client()
            raw, usage = llm_parse(text, client, previous)
            return ParseResult(spec=normalize(raw), source="llm", usage=usage)
        except Exception as exc:  # any API, network or format problem -> fallback
            error = f"{type(exc).__name__}: {exc}"
    else:
        error = "LLM disabled (no ANTHROPIC_API_KEY or use_llm=False)"

    raw = _merge_previous(keyword_parse(text), previous)
    return ParseResult(spec=normalize(raw), source="fallback", error=error)
