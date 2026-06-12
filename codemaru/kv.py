"""Shared Vercel KV (Upstash Redis) REST helper.

Centralizes credential lookup and the REST round-trip used by the shared summary
cache. Callers treat every call as best-effort (a KV outage must never break card
rendering), so this module stays deliberately thin and unopinionated.

The same KV store also backs adoption tracking (``analytics.py``); the two use
disjoint key namespaces (``summary:`` / ``stale:`` vs ``codemaru:users:*``), so a
single database serves both without collision.
"""

from __future__ import annotations

from typing import Any

import httpx

from codemaru.settings import get_settings


def credentials() -> tuple[str, str] | None:
    """Return (base_url, token) when KV is configured, else None (use fallback)."""
    settings = get_settings()
    if settings.kv_rest_api_url and settings.kv_rest_api_token:
        return settings.kv_rest_api_url.rstrip("/"), settings.kv_rest_api_token
    return None


# One reused client per process so the hot-path cache read keeps the TLS
# connection warm instead of re-handshaking on every request. The instance-bound
# client is cleaned up when the serverless instance is recycled.
_client: httpx.AsyncClient | None = None


def _http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=get_settings().kv_timeout_seconds)
    return _client


async def command(base: str, token: str, *args: str) -> Any:
    """Run one Upstash REST command (passed as a JSON-array body) and return its
    ``result``. Raises on network/HTTP errors so the caller can fall back."""
    resp = await _http_client().post(
        base, json=list(args), headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    return resp.json().get("result")
