"""solved.ac adapter (public API).

Uses the public solved.ac v3 endpoints (no BOJ scraping):
- ``user/show`` for tier, rating, solved count, and class
- ``user/problem_stats`` for the solved-by-difficulty distribution

solved.ac sits behind Cloudflare, which rejects plain-Python TLS fingerprints
(``httpx``/``curl`` get a 403 "Just a moment…" challenge regardless of headers or
IP). So this adapter uses ``curl_cffi`` with Chrome impersonation — a real
browser TLS/JA3 fingerprint — to read the public API. If the profile loads but
the distribution call fails, the snapshot is still ``ok`` with a zeroed
distribution; any other failure degrades to ``unavailable``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from curl_cffi.requests import AsyncSession

from codemaru.models.snapshot import (
    DifficultyDistribution,
    PlatformStatus,
    SolvedAcSnapshot,
)

SHOW_URL = "https://solved.ac/api/v3/user/show"
STATS_URL = "https://solved.ac/api/v3/user/problem_stats"

# solved.ac level → coarse difficulty band (level 0 is Unrated and ignored).
_BANDS = [
    (1, 5, "bronze"),
    (6, 10, "silver"),
    (11, 15, "gold"),
    (16, 20, "platinum"),
    (21, 25, "diamond"),
    (26, 30, "ruby"),
]


def _unavailable(handle: str, note: str, fetched_at: datetime) -> SolvedAcSnapshot:
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


def _band_for(level: int) -> str | None:
    for low, high, name in _BANDS:
        if low <= level <= high:
            return name
    return None


def parse_difficulty(stats: list[dict[str, Any]]) -> DifficultyDistribution:
    """Sum solved counts per difficulty band from the problem_stats payload."""
    totals = {name: 0 for _, _, name in _BANDS}
    for entry in stats:
        band = _band_for(int(entry.get("level", 0)))
        if band is not None:
            totals[band] += int(entry.get("solved", 0))
    return DifficultyDistribution(**totals)


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
    try:
        # impersonate a real Chrome TLS/JA3 fingerprint to pass Cloudflare.
        async with AsyncSession(impersonate="chrome", timeout=timeout) as session:
            show_resp = await session.get(SHOW_URL, params={"handle": handle})
            if show_resp.status_code != 200:
                return _unavailable(handle, f"http {show_resp.status_code}", fetched_at)
            show = show_resp.json()
            if not isinstance(show, dict) or "tier" not in show:
                return _unavailable(handle, "unexpected response", fetched_at)

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
        return _unavailable(handle, "request failed", fetched_at)
