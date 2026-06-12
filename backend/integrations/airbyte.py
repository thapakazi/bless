"""Airbyte Cloud integration — thin client over the v1 REST API.

Auth model: OAuth 2.0 client credentials. We POST `client_id` + `client_secret`
to /v1/applications/token, cache the bearer token, refresh on 401.

We intentionally use httpx directly rather than the `airbyte-api` SDK — the SDK
wraps `requests` and a forest of generated dataclasses, while we just need JSON
in / JSON out for a handful of endpoints. Keeps the demo path debuggable.

Pattern (is_available + lazy init + log-and-no-op on missing creds) follows
`backend/integrations/langfuse.py`.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger("bless.airbyte")


API_BASE = "https://api.airbyte.com/v1"
TOKEN_URL = f"{API_BASE}/applications/token"
# Airbyte tokens last ~15 min; refresh ~60s early to avoid edge races.
_TOKEN_TTL_SECONDS = 15 * 60 - 60


class AirbyteError(RuntimeError):
    """Raised when Airbyte returns a non-success status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


_token_lock = threading.Lock()
_token: str | None = None
_token_expires_at: float = 0.0


def is_available() -> bool:
    """True iff Airbyte Cloud OAuth creds are configured."""
    s = get_settings()
    return bool(s.airbyte_client_id and s.airbyte_client_secret)


def _fetch_token() -> str:
    """Exchange client credentials for a bearer token. Caller holds _token_lock."""
    global _token, _token_expires_at
    s = get_settings()
    if not is_available():
        log.info("airbyte: client creds absent — integration disabled")
        raise AirbyteError(401, "airbyte: client_id/client_secret not configured")

    payload = {
        "client_id": s.airbyte_client_id,
        "client_secret": s.airbyte_client_secret,
        "grant_type": "client_credentials",
    }
    log.info("airbyte: requesting new access token")
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(TOKEN_URL, json=payload)
    if resp.status_code >= 400:
        # Don't echo the secret. Just status + Airbyte's error body (which
        # typically contains only the error reason, not the creds).
        log.error("airbyte token request failed: %s %s", resp.status_code, resp.text[:300])
        raise AirbyteError(resp.status_code, f"airbyte token endpoint returned {resp.status_code}")
    body = resp.json()
    access_token = body.get("access_token")
    if not access_token:
        raise AirbyteError(500, "airbyte token endpoint returned no access_token")
    _token = access_token
    _token_expires_at = time.time() + _TOKEN_TTL_SECONDS
    return access_token


def _get_token(force_refresh: bool = False) -> str:
    """Return a valid bearer token, refreshing if needed."""
    global _token, _token_expires_at
    with _token_lock:
        if force_refresh or _token is None or time.time() >= _token_expires_at:
            return _fetch_token()
        return _token


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> Any:
    """Make an authenticated request to Airbyte, refreshing the token on 401.

    Returns parsed JSON (dict / list) on 2xx. Raises AirbyteError otherwise.
    """
    url = f"{API_BASE}{path}"
    token = _get_token()

    def _call(bearer: str) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=30.0) as client:
            return client.request(method, url, params=params, json=json, headers=headers)

    resp = _call(token)
    if resp.status_code == 401:
        log.info("airbyte: 401 — refreshing token and retrying once")
        token = _get_token(force_refresh=True)
        resp = _call(token)

    if resp.status_code >= 400:
        body_preview = resp.text[:500]
        log.warning("airbyte %s %s -> %s: %s", method, path, resp.status_code, body_preview)
        raise AirbyteError(resp.status_code, f"airbyte {method} {path}: {body_preview}")

    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


# -------- Workspaces --------

def list_workspaces() -> list[dict[str, Any]]:
    """List workspaces the OAuth app has access to."""
    body = _request("GET", "/workspaces")
    return body.get("data", []) if isinstance(body, dict) else []


# -------- Sources / Destinations / Connections --------

def list_sources(workspace_id: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if workspace_id:
        params["workspaceIds"] = workspace_id
    body = _request("GET", "/sources", params=params or None)
    return body.get("data", []) if isinstance(body, dict) else []


def list_destinations(workspace_id: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if workspace_id:
        params["workspaceIds"] = workspace_id
    body = _request("GET", "/destinations", params=params or None)
    return body.get("data", []) if isinstance(body, dict) else []


def list_connections(workspace_id: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if workspace_id:
        params["workspaceIds"] = workspace_id
    body = _request("GET", "/connections", params=params or None)
    return body.get("data", []) if isinstance(body, dict) else []


def get_connection(connection_id: str) -> dict[str, Any]:
    return _request("GET", f"/connections/{connection_id}")


# -------- Jobs --------

def trigger_sync(connection_id: str) -> dict[str, Any]:
    """Kick off a sync job for a connection. Returns the job object."""
    payload = {"connectionId": connection_id, "jobType": "sync"}
    return _request("POST", "/jobs", json=payload)


def get_job_status(job_id: str | int) -> dict[str, Any]:
    return _request("GET", f"/jobs/{job_id}")


def list_jobs(
    connection_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    if connection_id:
        params["connectionId"] = connection_id
    body = _request("GET", "/jobs", params=params)
    return body.get("data", []) if isinstance(body, dict) else []


# -------- Source definitions / catalog --------

def list_source_definitions(workspace_id: str | None = None) -> list[dict[str, Any]]:
    """List source connector types available to the workspace.

    Airbyte Cloud's public REST API exposes connector definitions via the
    `/source_definitions` endpoint scoped to a workspace. If unavailable in a
    given tenant, callers should handle the 404 gracefully.
    """
    params: dict[str, Any] = {}
    if workspace_id:
        params["workspaceIds"] = workspace_id
    body = _request("GET", "/source_definitions", params=params or None)
    return body.get("data", []) if isinstance(body, dict) else []
