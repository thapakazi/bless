"""Langfuse tracing — generations + spans nested under one trace per job.

When LANGFUSE_PUBLIC_KEY/SECRET_KEY are absent, all hooks become no-ops so the
caller code is identical whether tracing is on or off.

Usage shape:
    with job_context(job_id):                # opens trace
        with trace_span("investigate"):      # span on trace
            ...
            observe_generation(name="enrich_vendor", ...)   # generation under span
"""

from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any

from ..config import get_settings

log = logging.getLogger("bless.langfuse")


_initialized = False
_client = None
# _current_trace: always the top-level trace for the job (used by
#   update_current_trace and log_event so trace-level data lands on the trace).
# _current_parent: the closest enclosing observation (trace OR span). New
#   spans/generations attach here so nesting tracks the call stack.
_current_trace: contextvars.ContextVar = contextvars.ContextVar(
    "bless_lf_trace", default=None
)
_current_parent: contextvars.ContextVar = contextvars.ContextVar(
    "bless_lf_parent", default=None
)
_current_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "bless_lf_job", default=None
)


def _maybe_init() -> None:
    global _initialized, _client
    if _initialized:
        return
    _initialized = True
    s = get_settings()
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        log.info("langfuse: keys absent — tracing is a no-op")
        return
    try:
        from langfuse import Langfuse  # type: ignore

        _client = Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host,
        )
        log.info("langfuse: client initialized (host=%s)", s.langfuse_host)
    except Exception as e:
        log.warning("langfuse: init failed (%s); falling back to no-op", e)
        _client = None


def is_enabled() -> bool:
    _maybe_init()
    return _client is not None


def current_job_id() -> str | None:
    return _current_job_id.get()


def update_current_trace(
    *,
    input: Any | None = None,
    output: Any | None = None,
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> None:
    """Update the open job trace with input/output/tags/metadata.

    No-op outside a job_context or when Langfuse is disabled. Useful for
    setting trace-level summary fields once you know the result of a job.
    """
    parent = _current_trace.get()
    if parent is None:
        return
    payload: dict[str, Any] = {}
    if input is not None:
        payload["input"] = input
    if output is not None:
        payload["output"] = output
    if tags is not None:
        payload["tags"] = tags
    if metadata is not None:
        payload["metadata"] = metadata
    if not payload:
        return
    try:
        parent.update(**payload)
    except Exception as e:
        log.warning("langfuse trace update failed: %s", e)


@contextmanager
def job_context(
    job_id: str, *, name: str = "bless_run", metadata: dict | None = None
):
    """Open the per-job trace. All spans/generations inside nest under it.

    Also sets a ContextVar for `job_id` so downstream Claude calls can attach
    themselves without the orchestrator threading `job_id` through every layer.
    """
    _maybe_init()
    tok_job = _current_job_id.set(job_id)
    trace = None
    if _client is not None:
        try:
            trace = _client.trace(
                name=name,
                id=job_id,
                session_id=job_id,
                metadata=metadata or {},
            )
        except Exception as e:
            log.warning("langfuse trace open failed: %s", e)
            trace = None
    tok_trace = _current_trace.set(trace)
    tok_parent = _current_parent.set(trace)
    t0 = time.perf_counter()
    try:
        yield trace
    finally:
        dt = (time.perf_counter() - t0) * 1000
        log.info("trace %s done in %.0fms (job_id=%s)", name, dt, job_id)
        _current_job_id.reset(tok_job)
        _current_parent.reset(tok_parent)
        _current_trace.reset(tok_trace)
        if _client is not None:
            try:
                _client.flush()
            except Exception:
                pass


@contextmanager
def trace_span(
    name: str, trace_id: str | None = None, metadata: dict | None = None
):
    """Open a span on the active trace. If called outside a job_context,
    falls back to a standalone trace keyed by `trace_id`.

    While the span is open it becomes the active parent in `_current_trace`,
    so any `observe_generation` or nested `trace_span` calls inside the
    `with` block nest under THIS span (not the outer trace).
    """
    _maybe_init()
    t0 = time.perf_counter()
    parent = _current_parent.get()
    span = None
    if _client is not None:
        try:
            if parent is not None:
                span = parent.span(name=name, metadata=metadata or {})
            else:
                span = _client.trace(
                    name=name,
                    id=trace_id,
                    session_id=trace_id,
                    metadata=metadata or {},
                )
        except Exception as e:
            log.warning("langfuse span open failed: %s", e)
            span = None
    tok = _current_parent.set(span) if span is not None else None
    try:
        yield span
    finally:
        if tok is not None:
            _current_parent.reset(tok)
        dt = (time.perf_counter() - t0) * 1000
        log.info("span %s done in %.0fms (trace_id=%s)", name, dt, trace_id)
        if span is not None:
            try:
                span.end()
            except Exception:
                pass


def trace(name: str):
    """Decorator wrapping a function in a Langfuse span (no-op if disabled)."""

    def deco(fn):
        @wraps(fn)
        def wrap(*args, **kwargs):
            trace_id = kwargs.get("job_id") or (args[0] if args else None)
            with trace_span(name, trace_id=str(trace_id) if trace_id else None):
                return fn(*args, **kwargs)

        return wrap

    return deco


def log_event(name: str, metadata: dict[str, Any] | None = None) -> None:
    _maybe_init()
    log.info("event %s %s", name, metadata or {})
    if _client is None:
        return
    parent = _current_parent.get()
    try:
        if parent is not None:
            parent.event(name=name, metadata=metadata or {})
        else:
            _client.event(name=name, metadata=metadata or {})
    except Exception as e:
        log.debug("langfuse log_event failed: %s", e)


def observe_generation(
    *,
    name: str,
    model: str,
    input_payload: Any,
    output: Any,
    usage: dict[str, int] | None = None,
    metadata: dict | None = None,
) -> None:
    """Log an LLM call as a Langfuse generation.

    Nests under the active trace (set by `job_context`) when one is in scope;
    otherwise creates a standalone trace tagged with the current job_id.

    Anthropic `usage` keys (`input_tokens`, `output_tokens`,
    `cache_creation_input_tokens`, `cache_read_input_tokens`) are mapped to
    Langfuse's usage schema; cache fields land in metadata so prompt-cache
    behavior is visible per call.
    """
    _maybe_init()
    if _client is None:
        return
    usage = usage or {}
    md = dict(metadata or {})
    md["cache_creation_input_tokens"] = usage.get(
        "cache_creation_input_tokens", 0
    )
    md["cache_read_input_tokens"] = usage.get("cache_read_input_tokens", 0)
    lf_usage = {
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "total": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        "unit": "TOKENS",
    }
    parent = _current_parent.get()
    job_id = _current_job_id.get()
    try:
        if parent is not None:
            gen = parent.generation(
                name=name,
                model=model,
                input=input_payload,
                output=output,
                usage=lf_usage,
                metadata=md,
            )
        else:
            standalone = _client.trace(
                name=name,
                session_id=job_id,
                metadata={"job_id": job_id} if job_id else {},
            )
            gen = standalone.generation(
                name=name,
                model=model,
                input=input_payload,
                output=output,
                usage=lf_usage,
                metadata=md,
            )
        gen.end()
    except Exception as e:
        log.warning("langfuse generation log failed: %s", e)
