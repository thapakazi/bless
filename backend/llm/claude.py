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

Each call is also logged to Langfuse as a generation (no-op if keys absent),
including the prompt-cache token fields so cache hit rate is visible per call.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable

import anthropic
from anthropic.types import MessageParam, TextBlockParam

from ..config import get_settings
from ..integrations.langfuse import observe_generation

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
    *,
    vendor_name: str | None = None,
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
    observe_generation(
        name=f"enrich:{vendor_name}" if vendor_name else "enrich_vendor",
        model=s.claude_model_enricher,
        input_payload={"system": system_blocks, "user": user_message},
        output=text,
        usage=usage,
        metadata={
            "max_tokens": ENRICHER_MAX_TOKENS,
            "role": "enricher",
            "vendor_name": vendor_name,
        },
    )
    return _parse_json_loose(text), usage


def messages_create_traced(
    *,
    client: anthropic.Anthropic,
    name: str,
    model: str,
    system: Any,
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int,
    metadata: dict | None = None,
):
    """Thin wrapper around `client.messages.create` that emits a Langfuse
    generation.

    Used by the investigator (which runs its own tool-use loop) so each
    Claude round is captured with full input/output/usage. Returns the raw
    Anthropic response — callers still need to inspect `.content` for
    tool_use blocks etc.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
    resp = client.messages.create(**kwargs)
    output_payload = [
        _block_to_dict(b) for b in resp.content
    ] if resp.content else None
    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_creation_input_tokens": resp.usage.cache_creation_input_tokens or 0,
        "cache_read_input_tokens": resp.usage.cache_read_input_tokens or 0,
    }
    md = dict(metadata or {})
    md.setdefault("max_tokens", max_tokens)
    md["stop_reason"] = resp.stop_reason
    if tools:
        md["tools"] = [t.get("name") or t.get("type") for t in tools]
    observe_generation(
        name=name,
        model=model,
        input_payload={"system": system, "messages": messages},
        output=output_payload,
        usage=usage,
        metadata=md,
    )
    return resp


def _block_to_dict(b) -> dict[str, Any]:
    """Serialize an Anthropic content block (text / tool_use / tool_result)."""
    t = getattr(b, "type", "unknown")
    if t == "text":
        return {"type": "text", "text": getattr(b, "text", "")}
    if t == "tool_use":
        return {
            "type": "tool_use",
            "id": getattr(b, "id", None),
            "name": getattr(b, "name", None),
            "input": getattr(b, "input", None),
        }
    if t == "tool_result":
        return {
            "type": "tool_result",
            "tool_use_id": getattr(b, "tool_use_id", None),
            "content": getattr(b, "content", None),
        }
    return {"type": t, "repr": repr(b)[:500]}


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
    text = _first_text(resp.content)
    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_creation_input_tokens": resp.usage.cache_creation_input_tokens or 0,
        "cache_read_input_tokens": resp.usage.cache_read_input_tokens or 0,
    }
    observe_generation(
        name="generate_report",
        model=s.claude_model_reporter,
        input_payload={"system": system, "user": user},
        output=text,
        usage=usage,
        metadata={"max_tokens": REPORTER_MAX_TOKENS, "role": "reporter"},
    )
    data = _parse_json_loose(text)
    return (
        data.get("narrative_summary", "").strip(),
        data.get("top_action", "").strip(),
    )


def chat_stream(
    system: str,
    messages: list[MessageParam],
) -> Iterable[str]:
    """Streaming chat for /api/chat. Yields text deltas.

    Emits a single Langfuse generation once the stream completes (with the
    full accumulated text and final usage), in a `finally` so partial streams
    are still recorded.
    """
    s = get_settings()
    buf: list[str] = []
    usage: dict[str, int] = {}
    try:
        with _get_client().messages.stream(
            model=s.claude_model_chat,
            max_tokens=2048,
            system=system,
            messages=messages,
        ) as stream:
            for chunk in stream.text_stream:
                buf.append(chunk)
                yield chunk
            final = stream.get_final_message()
            usage = {
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
                "cache_creation_input_tokens": final.usage.cache_creation_input_tokens or 0,
                "cache_read_input_tokens": final.usage.cache_read_input_tokens or 0,
            }
    finally:
        observe_generation(
            name="chat",
            model=s.claude_model_chat,
            input_payload={"system": system, "messages": list(messages)},
            output="".join(buf),
            usage=usage,
            metadata={"max_tokens": 2048, "role": "chat", "streamed": True},
        )


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
