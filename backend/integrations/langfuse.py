"""Langfuse tracing — real spans if keys are set, no-op decorators otherwise.

Callers use `@trace("step_name")` and `log_event("name", {...})`. The shape of
caller code is identical with or without keys; this keeps adding observability
later a one-line change.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any

from ..config import get_settings

log = logging.getLogger("bless.langfuse")


_initialized = False
_client = None


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
        log.info("langfuse: client initialized")
    except Exception as e:
        log.warning("langfuse: init failed (%s); falling back to no-op", e)
        _client = None


def is_enabled() -> bool:
    _maybe_init()
    return _client is not None


@contextmanager
def trace_span(name: str, trace_id: str | None = None, metadata: dict | None = None):
    """Context manager that opens a Langfuse span (or logs to stdout)."""
    _maybe_init()
    t0 = time.perf_counter()
    span = None
    if _client is not None:
        try:
            span = _client.trace(name=name, id=trace_id, metadata=metadata or {})
        except Exception as e:
            log.warning("langfuse span open failed: %s", e)
            span = None
    try:
        yield span
    finally:
        dt = (time.perf_counter() - t0) * 1000
        log.info("trace %s done in %.0fms (trace_id=%s)", name, dt, trace_id)
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
    try:
        _client.event(name=name, metadata=metadata or {})
    except Exception as e:
        log.debug("langfuse log_event failed: %s", e)
