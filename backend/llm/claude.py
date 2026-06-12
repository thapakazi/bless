"""Claude (Anthropic) client used by enricher, reporter, and chat.

Design notes
------------
- Enricher: structured per-vendor calls. Heavy reuse of a system prompt, so we
  enable prompt caching (`cache_control: ephemeral`) on the system blocks. The
  system content includes vendor-seed reference data so the prefix exceeds
  Sonnet 4.6's 2048-token cache minimum (a bare "be a SaaS pricing expert"
  prompt would not cache).
- Reporter: one-shot narrative on the full report payload. Opus 4.7.
- Chat: streaming Q&A. Opus 4.7. Yields text deltas.

If ANTHROPIC_API_KEY is unset, `is_available()` returns False and callers
should fall back to seed data / templated output.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable

import anthropic
from anthropic.types import MessageParam, TextBlockParam

from ..config import get_settings

log = logging.getLogger("bless.claude")

_client: anthropic.Anthropic | None = None

# Conservative output ceilings. Streaming is required for higher values
# (see Anthropic SDK timeout guard).
ENRICHER_MAX_TOKENS = 1024
REPORTER_MAX_TOKENS = 2048


def is_available() -> bool:
    return bool(get_settings().anthropic_api_key)


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    return _client


def enrich_vendor(
    system_blocks: list[TextBlockParam],
    user_message: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    """One enricher call. Returns (parsed JSON, usage).

    `system_blocks` is built once per audit by the caller and includes a
    `cache_control: ephemeral` marker on the last block. The same list is
    passed for all 15 vendor calls so the prefix matches and caches.
    """
    s = get_settings()
    resp = _get_client().messages.create(
        model=s.claude_model_enricher,
        max_tokens=ENRICHER_MAX_TOKENS,
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
    )
    text = _first_text(resp.content)
    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_creation_input_tokens": resp.usage.cache_creation_input_tokens or 0,
        "cache_read_input_tokens": resp.usage.cache_read_input_tokens or 0,
    }
    return _parse_json_loose(text), usage


def generate_report_narrative(
    system: str,
    report_payload: dict[str, Any],
) -> tuple[str, str]:
    """Reporter call. Returns (narrative_summary, top_action)."""
    s = get_settings()
    user = (
        "Generate the narrative_summary and top_action for this Bless report.\n\n"
        f"REPORT:\n{json.dumps(report_payload, default=str)}\n\n"
        "Return ONLY a JSON object: "
        '{"narrative_summary": "...", "top_action": "..."}'
    )
    resp = _get_client().messages.create(
        model=s.claude_model_reporter,
        max_tokens=REPORTER_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    data = _parse_json_loose(_first_text(resp.content))
    return (
        data.get("narrative_summary", "").strip(),
        data.get("top_action", "").strip(),
    )


def chat_stream(
    system: str,
    messages: list[MessageParam],
) -> Iterable[str]:
    """Streaming chat for /api/chat. Yields text deltas."""
    s = get_settings()
    with _get_client().messages.stream(
        model=s.claude_model_chat,
        max_tokens=2048,
        system=system,
        messages=messages,
    ) as stream:
        for chunk in stream.text_stream:
            yield chunk


# --- helpers --------------------------------------------------------------


def _first_text(content) -> str:
    for block in content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _parse_json_loose(raw: str) -> dict[str, Any]:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    # Try direct parse; if model wrapped in prose, find the first JSON object.
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except json.JSONDecodeError as e:
            log.warning("Claude returned malformed JSON: %s", e)
    return {}
