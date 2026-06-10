"""Best-effort adoption tracking via Vercel KV (Upstash Redis REST).

Counts the distinct GitHub handles whose card GitHub's image proxy (Camo) has
fetched — i.e. developers who actually embedded a codemaru card in a rendered
README. (Static GitHub Action users never hit this endpoint, so they are not
counted.)

Everything here is best-effort: if KV is not configured (local dev, CI) or a
call fails or times out, it degrades to a no-op / zero and never affects card
rendering. The handle is the only thing stored — a public username, lower-cased
for de-duplication — never viewer IPs or headers (Camo hides viewers anyway).
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

import httpx

from codemaru.settings import get_settings

# Single Redis SET of distinct embedded-card handles; SCARD is the badge number.
_USERS_KEY = "codemaru:users"

# In-process dedupe: skip re-recording a handle already seen recently on this
# warm instance. Caps redundant Redis commands from repeated or spoofed Camo
# fetches (Upstash's free tier has a monthly command budget). Best-effort and
# bounded; correctness is unaffected since SADD is idempotent regardless.
_DEDUPE_TTL = 6 * 60 * 60  # seconds
_DEDUPE_MAX = 4096
_seen: dict[str, float] = {}


def is_camo(user_agent: str | None) -> bool:
    """True when the request came from GitHub's image proxy (a real embed).

    GitHub fetches README images through Camo (User-Agent contains ``camo``),
    so this filters out generator previews from the hosted site.
    """
    return user_agent is not None and "camo" in user_agent.lower()


def _credentials() -> tuple[str, str] | None:
    settings = get_settings()
    if settings.kv_rest_api_url and settings.kv_rest_api_token:
        return settings.kv_rest_api_url.rstrip("/"), settings.kv_rest_api_token
    return None


async def _command(base: str, token: str, *args: str) -> Any:
    """Run one Upstash REST command (as a JSON-array body) and return its result.

    Passing the command in the body avoids any URL-encoding pitfalls with the
    arguments, and ``raise_for_status`` surfaces auth/quota errors to the caller
    (which still swallows them — tracking must never be fatal).
    """
    timeout = get_settings().analytics_timeout_seconds
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            base, json=list(args), headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json().get("result")


def _seen_recently(handle: str) -> bool:
    """True if handle was recorded recently (skip it); else mark it and return False."""
    now = time.monotonic()
    expiry = _seen.get(handle)
    if expiry is not None and expiry > now:
        return True
    if len(_seen) >= _DEDUPE_MAX:  # evict expired, then hard-reset if still full
        for key, exp in list(_seen.items()):
            if exp <= now:
                del _seen[key]
        if len(_seen) >= _DEDUPE_MAX:
            _seen.clear()
    _seen[handle] = now + _DEDUPE_TTL
    return False


async def record_embed(handle: str) -> None:
    """Add a handle to the distinct-users set (idempotent). No-op without KV."""
    creds = _credentials()
    if creds is None:
        return
    handle = handle.lower()
    if _seen_recently(handle):
        return
    base, token = creds
    # Best-effort: a KV error/timeout must never break card rendering.
    with contextlib.suppress(Exception):
        await _command(base, token, "SADD", _USERS_KEY, handle)


async def usage_count() -> int:
    """Distinct embedded-user count (SCARD). Returns 0 without KV or on failure."""
    creds = _credentials()
    if creds is None:
        return 0
    base, token = creds
    try:
        result = await _command(base, token, "SCARD", _USERS_KEY)
        return int(result or 0)
    except Exception:  # noqa: BLE001 - tracking is best-effort, never fatal
        return 0
