"""Card service: turns a validated ProfileInput into a CodemaruSummary.

This is where input → (cache | adapters) → scoring → summary is coordinated, so
routes stay thin. Fixture mode serves deterministic sample data; live mode
fetches the platforms concurrently. Both go through the same cache boundary.

The cache is keyed by profile only (not theme/compact): those affect rendering,
not the underlying data, and rendering is cheap.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from codemaru.adapters import fetch_github, fetch_leetcode, fetch_solvedac
from codemaru.adapters.base import build_client
from codemaru.cache import InMemoryCache
from codemaru.core.scoring import SCORE_VERSION
from codemaru.core.summary import build_summary
from codemaru.fixtures.demo import FIXED_TIMESTAMP, resolve_fixture_bundle
from codemaru.models.input import ProfileInput
from codemaru.models.snapshot import PlatformStatus, SnapshotBundle
from codemaru.models.summary import CodemaruSummary
from codemaru.settings import Settings, get_settings

# Live GitHub/solved.ac/LeetCode adapters are implemented. Fixture mode stays the
# default so local dev and CI need no secrets or network.
LIVE_ADAPTERS_AVAILABLE = True

# Short-lived response cache (keyed by profile) and a longer-lived store of the
# last fully successful summary used for stale fallback during outages.
_cache = InMemoryCache()
_stale = InMemoryCache()


class LiveDataUnavailableError(RuntimeError):
    """Raised when live data is requested but no adapters are available."""


def effective_mode() -> str:
    """The mode the service can actually serve right now (never a lie)."""
    settings = get_settings()
    if settings.fixture_mode:
        return "fixture"
    return "live" if LIVE_ADAPTERS_AVAILABLE else "unavailable"


def _cache_key(profile: ProfileInput) -> str:
    return f"summary:v{SCORE_VERSION}:{profile.github}|{profile.boj}|{profile.leetcode}"


async def get_summary(profile: ProfileInput) -> CodemaruSummary:
    """Return the summary for a profile, using the cache when warm.

    Raises LiveDataUnavailableError if live data is requested
    (``FIXTURE_MODE=false``) but no adapters are available, so fixture data is
    never presented as if it were live.
    """
    settings = get_settings()
    if not settings.fixture_mode and not LIVE_ADAPTERS_AVAILABLE:
        raise LiveDataUnavailableError("live adapters are unavailable; set FIXTURE_MODE=true")

    key = _cache_key(profile)
    cached = _cache.get(key)
    if cached is not None:
        return CodemaruSummary.model_validate_json(cached)

    if settings.fixture_mode:
        summary = _build_fixture(profile)
    else:
        summary = await _build_live(profile, settings)
        summary = _apply_stale_fallback(key, summary, settings)

    _store(key, summary, settings)
    return summary


def _apply_stale_fallback(
    key: str, summary: CodemaruSummary, settings: Settings
) -> CodemaruSummary:
    """On a fully-successful build, refresh the last-good store; on a degraded
    build, fall back to the last good summary if one is still retained.

    This keeps a user's card intact through a transient platform outage instead
    of showing a suddenly-degraded score for the cache lifetime.
    """
    if summary.overall_status is PlatformStatus.OK:
        _stale.set(key, summary.model_dump_json(), settings.stale_ttl_seconds)
        return summary
    last_good = _stale.get(key)
    if last_good is not None:
        return CodemaruSummary.model_validate_json(last_good)
    return summary


def _store(key: str, summary: CodemaruSummary, settings: Settings) -> None:
    # Cache the field-name form so it round-trips back through validation; the
    # JSON endpoint serializes with aliases separately for the public response.
    # Degraded results get a short TTL so a transient failure isn't pinned for
    # the full cache lifetime.
    ttl = (
        settings.cache_ttl_seconds
        if summary.overall_status is PlatformStatus.OK
        else settings.negative_cache_ttl_seconds
    )
    _cache.set(key, summary.model_dump_json(), ttl)


def _build_fixture(profile: ProfileInput) -> CodemaruSummary:
    bundle = resolve_fixture_bundle(profile)
    return build_summary(profile, bundle, FIXED_TIMESTAMP)


async def _build_live(profile: ProfileInput, settings: Settings) -> CodemaruSummary:
    """Fetch all requested platforms concurrently and assemble the summary.

    Adapters never raise — each maps failures to an ``unavailable`` snapshot — so
    one platform failing degrades the card instead of breaking the request.
    """
    fetched_at = datetime.now(UTC)
    async with build_client(settings.adapter_timeout_seconds) as client:
        # create_task schedules them concurrently; awaiting in turn still runs
        # them in parallel and keeps each result strongly typed.
        gh_task = asyncio.create_task(
            fetch_github(
                profile.github, token=settings.github_token, fetched_at=fetched_at, client=client
            )
        )
        # solved.ac uses its own curl_cffi session (Cloudflare blocks httpx), so
        # it takes a timeout rather than the shared client.
        sa_task = (
            asyncio.create_task(
                fetch_solvedac(
                    profile.boj,
                    fetched_at=fetched_at,
                    timeout=settings.adapter_timeout_seconds,
                )
            )
            if profile.boj
            else None
        )
        lc_task = (
            asyncio.create_task(
                fetch_leetcode(profile.leetcode, fetched_at=fetched_at, client=client)
            )
            if profile.leetcode
            else None
        )

        bundle = SnapshotBundle(github=await gh_task)
        if sa_task is not None:
            bundle.solvedac = await sa_task
        if lc_task is not None:
            bundle.leetcode = await lc_task

    return build_summary(profile, bundle, fetched_at)


def clear_cache() -> None:
    """Drop all cached and last-successful summaries (used in tests)."""
    _cache.clear()
    _stale.clear()
