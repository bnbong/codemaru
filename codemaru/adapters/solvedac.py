"""solved.ac adapter (public API).

Uses the public solved.ac v3 endpoints (no BOJ scraping):
- ``user/show`` for tier, rating, solved count, and class
- ``user/problem_stats`` for the solved-by-difficulty distribution

solved.ac sits behind Cloudflare, which rejects plain-Python TLS fingerprints
(``httpx``/``curl`` get a 403 "Just a moment…" challenge regardless of headers or
IP). So this adapter uses ``curl_cffi`` with Chrome impersonation — a real
browser TLS/JA3 fingerprint — to read the public API. If the profile loads but
the distribution call fails, the snapshot is marked ``partial`` (profile metrics
kept, distribution zeroed); any other failure degrades to ``unavailable``.
"""

from __future__ import annotations

from datetime import datetime
from time import monotonic
from typing import Any

from curl_cffi.requests import AsyncSession

# The difficulty-band table moved to adapters/tiers.py so judges sharing the
# solved.ac tier scale can reuse it. Re-exported here so existing imports of
# ``solvedac.parse_difficulty`` (and the private helpers) keep working.
from codemaru.adapters.tiers import _BANDS, _band_for, parse_difficulty
from codemaru.models.snapshot import (
    PlatformStatus,
    SolvedAcSnapshot,
)
from codemaru.telemetry import log_adapter

SHOW_URL = "https://solved.ac/api/v3/user/show"
STATS_URL = "https://solved.ac/api/v3/user/problem_stats"

__all__ = [
    "SHOW_URL",
    "STATS_URL",
    "_BANDS",
    "_band_for",
    "fetch_solvedac",
    "parse_difficulty",
    "parse_solvedac",
    "unavailable_snapshot",
]


def unavailable_snapshot(handle: str, note: str, fetched_at: datetime) -> SolvedAcSnapshot:
    """An all-zero snapshot standing in for data this platform could not supply.

    Public so the service layer can substitute one when the card-build budget
    cuts a fetch short, without duplicating the field list."""
    return SolvedAcSnapshot(
        status=PlatformStatus.UNAVAILABLE,
        fetched_at=fetched_at,
        note=note,
        handle=handle,
        tier=0,
        rating=0,
        solved_count=0,
        class_level=0,
    )


def parse_solvedac(
    show: dict[str, Any],
    stats: list[dict[str, Any]] | None,
    handle: str,
    fetched_at: datetime,
) -> SolvedAcSnapshot:
    """Build a SolvedAcSnapshot from the user/show (+ optional stats) payloads.

    ``stats is None`` means the difficulty-distribution call failed: the profile
    metrics are still returned, but the snapshot is marked ``partial`` (and the
    distribution zeroed) so the missing Depth signal lowers confidence and shows
    up as partial data rather than silently distorting the score.
    """
    # solved.ac tiers run 0..30; clamp defensively against schema drift.
    tier = max(0, min(30, int(show.get("tier", 0))))
    status = PlatformStatus.OK if stats is not None else PlatformStatus.PARTIAL
    note = None if stats is not None else "difficulty distribution unavailable"
    return SolvedAcSnapshot(
        status=status,
        fetched_at=fetched_at,
        note=note,
        handle=show.get("handle", handle),
        tier=tier,
        rating=max(0, int(show.get("rating", 0))),
        solved_count=max(0, int(show.get("solvedCount", 0))),
        class_level=max(0, int(show.get("class", 0))),
        difficulty=parse_difficulty(stats or []),
    )


async def fetch_solvedac(
    handle: str,
    *,
    fetched_at: datetime,
    timeout: float,
) -> SolvedAcSnapshot:
    """Fetch a solved.ac snapshot, mapping any failure to ``unavailable``.

    Uses its own curl_cffi session (browser-impersonating TLS) rather than the
    shared httpx client, since httpx is blocked by Cloudflare here.
    """
    # A thin wrapper around the real fetch so every exit path — ok, partial,
    # unavailable — is logged from one place.
    started = monotonic()
    snapshot = await _fetch_solvedac(handle, fetched_at=fetched_at, timeout=timeout)
    log_adapter("solvedac", handle, status=snapshot.status, note=snapshot.note, started=started)
    return snapshot


async def _fetch_solvedac(
    handle: str,
    *,
    fetched_at: datetime,
    timeout: float,
) -> SolvedAcSnapshot:
    try:
        # impersonate a real Chrome TLS/JA3 fingerprint to pass Cloudflare.
        async with AsyncSession(impersonate="chrome", timeout=timeout) as session:
            show_resp = await session.get(SHOW_URL, params={"handle": handle})
            if show_resp.status_code != 200:
                return unavailable_snapshot(handle, f"http {show_resp.status_code}", fetched_at)
            show = show_resp.json()
            if not isinstance(show, dict) or "tier" not in show:
                return unavailable_snapshot(handle, "unexpected response", fetched_at)

            # The distribution is best-effort; a failure still yields an ok profile.
            stats: list[dict[str, Any]] | None = None
            try:
                stats_resp = await session.get(STATS_URL, params={"handle": handle})
                if stats_resp.status_code == 200 and isinstance(stats_resp.json(), list):
                    stats = stats_resp.json()
            except Exception:  # noqa: BLE001 - distribution is optional
                stats = None

            return parse_solvedac(show, stats, handle, fetched_at)
    except Exception:  # noqa: BLE001 - degrade gracefully on any network/schema error
        return unavailable_snapshot(handle, "request failed", fetched_at)
