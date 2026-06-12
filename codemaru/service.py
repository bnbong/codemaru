"""Card service: turns a validated ProfileInput into a CodemaruSummary.

This is where input → (cache | adapters) → scoring → summary is coordinated, so
routes stay thin. Fixture mode serves deterministic sample data; live mode
fetches the platforms concurrently. Both go through the same cache boundary.

The cache is keyed by profile only (not theme/compact): those affect rendering,
not the underlying data, and rendering is cheap.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

from pydantic import ValidationError

from codemaru import kv
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
#
# These in-memory stores are the fallback: when Vercel KV is configured the cache
# lives in Redis instead (shared across serverless instances, so a cold instance
# reuses a warm cache and skips the live fetch). Without KV — local dev, CI — or
# on any KV error, we transparently use these per-instance dicts and rendering is
# never affected.
_cache = InMemoryCache()
_stale = InMemoryCache()

# Redis key prefix for the stale-fallback store (the response cache uses the bare
# profile key). Keeps the two namespaces distinct within one shared KV database.
_STALE_PREFIX = "stale:"


class LiveDataUnavailableError(RuntimeError):
    """Raised when live data is requested but no adapters are available."""


async def _kv_get(memory: InMemoryCache, key: str) -> str | None:
    """Read from KV when configured, falling back to the in-memory cache on a KV
    miss-credentials/outage. The in-memory copy is a mirror of this instance's own
    writes, so a transient KV read failure still serves a warm instance instead of
    forcing a live rebuild."""
    creds = kv.credentials()
    if creds is None:
        return memory.get(key)
    try:
        result = await kv.command(*creds, "GET", key)
    except Exception:  # noqa: BLE001 - KV down -> use whatever this instance cached
        return memory.get(key)
    # A remote nil isn't authoritative here: an earlier SET may have failed (and
    # been suppressed) or the entry was evicted while this instance still holds a
    # valid mirror. Prefer the warm mirror so a write blip doesn't force a rebuild
    # on every request; memory.get returns None too on a genuine miss.
    if result is None:
        return memory.get(key)
    return str(result)


async def _kv_set(memory: InMemoryCache, key: str, value: str, ttl_seconds: float) -> None:
    """Always mirror into in-memory (so a warm instance survives a KV read blip),
    then best-effort write to KV when configured."""
    memory.set(key, value, ttl_seconds)
    creds = kv.credentials()
    if creds is None:
        return
    with contextlib.suppress(Exception):  # a failed KV write just leaves the local mirror
        await kv.command(*creds, "SET", key, value, "EX", str(max(1, int(ttl_seconds))))


async def _cache_read(key: str) -> str | None:
    return await _kv_get(_cache, key)


async def _cache_write(key: str, value: str, ttl_seconds: float) -> None:
    await _kv_set(_cache, key, value, ttl_seconds)


async def _stale_read(key: str) -> str | None:
    return await _kv_get(_stale, _STALE_PREFIX + key)


async def _stale_write(key: str, value: str, ttl_seconds: float) -> None:
    await _kv_set(_stale, _STALE_PREFIX + key, value, ttl_seconds)


def effective_mode() -> str:
    """The mode the service can actually serve right now (never a lie)."""
    settings = get_settings()
    if settings.fixture_mode:
        return "fixture"
    return "live" if LIVE_ADAPTERS_AVAILABLE else "unavailable"


def _cache_key(profile: ProfileInput) -> str:
    # Scope the key by SCORE_VERSION (scoring engine), deploy env (so a preview
    # deploy can't pollute production), and mode (fixture vs live data must never
    # share an entry). Absent handles serialize to "" — not the literal "None" —
    # so an unset handle and a real handle named "None" don't collide.
    settings = get_settings()
    mode = "fixture" if settings.fixture_mode else "live"
    boj = profile.boj or ""
    leetcode = profile.leetcode or ""
    return (
        f"summary:v{SCORE_VERSION}:{settings.vercel_env}:{mode}:{profile.github}|{boj}|{leetcode}"
    )


def _load_summary(raw: str) -> CodemaruSummary | None:
    """Parse a cached summary, treating an incompatible or corrupt entry as a
    miss instead of a 500.

    With a shared cache the value may have been written by a different deploy
    whose model schema differs (the key carries SCORE_VERSION, but model fields
    can change without bumping it). A bad entry just triggers a rebuild, which
    overwrites it.
    """
    try:
        return CodemaruSummary.model_validate_json(raw)
    except ValidationError:
        return None


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
    cached = await _cache_read(key)
    if cached is not None:
        restored = _load_summary(cached)
        if restored is not None:
            return restored
        # Incompatible/corrupt entry — fall through to rebuild, which overwrites it.

    if settings.fixture_mode:
        summary = _build_fixture(profile)
    else:
        summary = await _build_live(profile, settings)
        summary = await _apply_stale_fallback(key, summary, settings)

    await _store(key, summary, settings)
    return summary


async def _apply_stale_fallback(
    key: str, summary: CodemaruSummary, settings: Settings
) -> CodemaruSummary:
    """On a fully-successful build, refresh the last-good store; on a degraded
    build, fall back to the last good summary if one is still retained.

    This keeps a user's card intact through a transient platform outage instead
    of showing a suddenly-degraded score for the cache lifetime.
    """
    if summary.overall_status is PlatformStatus.OK:
        await _stale_write(key, summary.model_dump_json(), settings.stale_ttl_seconds)
        return summary
    last_good = await _stale_read(key)
    if last_good is not None:
        restored = _load_summary(last_good)
        if restored is not None:
            # Serve the last good summary, but mark it stale so JSON consumers and
            # the card footer can tell it isn't a fresh read.
            return restored.model_copy(update={"stale": True})
    return summary


async def _store(key: str, summary: CodemaruSummary, settings: Settings) -> None:
    # Cache the field-name form so it round-trips back through validation; the
    # JSON endpoint serializes with aliases separately for the public response.
    # Degraded results get a short TTL so a transient failure isn't pinned for
    # the full cache lifetime.
    ttl = (
        settings.cache_ttl_seconds
        if summary.overall_status is PlatformStatus.OK
        else settings.negative_cache_ttl_seconds
    )
    await _cache_write(key, summary.model_dump_json(), ttl)


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
