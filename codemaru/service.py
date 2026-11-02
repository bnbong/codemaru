"""Card service: turns a validated ProfileInput into a CodemaruSummary.

This is where input → (cache | adapters) → scoring → summary is coordinated, so
routes stay thin. Fixture mode serves deterministic sample data; live mode
fetches the platforms concurrently. Both go through the same cache boundary.

Two entry points share that boundary:

* ``get_summary`` — always answers with a summary built (or cached) right now.
  The CLI and anything that wants a fresh read use it.
* ``get_summary_stale_first`` — the web routes' path. On a response-cache miss
  it answers immediately with the last-good summary (marked stale) and hands
  the live rebuild back to the caller to run *after* the response is sent. A
  live build can take several seconds, and GitHub's image proxy (Camo) gives up
  at roughly 4s, so a synchronous rebuild showed a broken image on the first
  view of an expired card.

The cache is keyed by profile only (not theme/compact): those affect rendering,
not the underlying data, and rendering is cheap.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from time import monotonic
from typing import Any

from pydantic import ValidationError

from codemaru import kv
from codemaru.adapters import fetch_github, fetch_jungol, fetch_leetcode, fetch_solvedac
from codemaru.adapters.base import build_client
from codemaru.adapters.github import NOT_FOUND_NOTE as _GITHUB_NOT_FOUND_NOTE
from codemaru.adapters.github import unavailable_snapshot as github_unavailable
from codemaru.adapters.jungol import unavailable_snapshot as jungol_unavailable
from codemaru.adapters.leetcode import unavailable_snapshot as leetcode_unavailable
from codemaru.adapters.registry import JUDGES
from codemaru.adapters.solvedac import unavailable_snapshot as solvedac_unavailable
from codemaru.cache import InMemoryCache
from codemaru.core.scoring import SCORE_VERSION
from codemaru.core.summary import build_summary
from codemaru.fixtures.demo import FIXED_TIMESTAMP, resolve_fixture_bundle
from codemaru.models.input import ProfileInput
from codemaru.models.snapshot import (
    GitHubSnapshot,
    JudgeSnapshot,
    PlatformStatus,
    SnapshotBundle,
)
from codemaru.models.summary import CodemaruSummary
from codemaru.settings import Settings, get_settings
from codemaru.telemetry import elapsed_ms, log_event, log_exception

# A judge adapter: called with the handle plus keyword arguments that vary by
# platform (the shared client, or a timeout for adapters with their own session).
JudgeFetch = Callable[..., Coroutine[Any, Any, JudgeSnapshot]]

# Registry key → the adapter's "this platform produced nothing" constructor.
# Module-level (unlike the fetch map) because nothing monkeypatches these.
_JUDGE_UNAVAILABLE: dict[str, Callable[[str, str, datetime], JudgeSnapshot]] = {
    "solvedac": solvedac_unavailable,
    "leetcode": leetcode_unavailable,
    "jungol": jungol_unavailable,
}

# Note attached to a snapshot the card-build budget cut short, so a degraded card
# and its cached entry say *why* the platform is missing.
_BUDGET_NOTE = "timed out (card build budget)"

# Slice of the build budget reserved for scoring and summary assembly after the
# fetches return; GitHub's cooperative pagination deadline stops this much early.
_BUILD_DEADLINE_MARGIN = 0.5

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

# Cache keys whose background refresh this instance has already launched, mapped
# to when it was claimed (monotonic seconds). A burst of Camo hits for one
# expired card all miss the cache within the same second or two; without this
# each would start its own multi-second live build against the same platforms.
#
# Deliberately per-instance only. Across instances the refresh writes the served
# stale copy back to the response cache as its first step, so other instances
# get a (short-TTL) cache hit instead of a miss and don't start a refresh of
# their own. A dedicated KV lock would close the remaining sub-second window,
# but costs a KV round trip on every miss for a duplicate build that is
# harmless (both builds write the same fresh result).
_refreshing: dict[str, float] = {}

# Extra seconds a refresh claim is honoured beyond the refresh's own worst case
# (see _refresh_claim_seconds). After that the claim is treated as abandoned —
# e.g. a route rendered an error card and dropped the background work, or the
# instance was frozen mid-refresh — so the next miss can try again.
_REFRESH_CLAIM_MARGIN = 5.0


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
    except Exception as exc:  # noqa: BLE001 - KV down -> use whatever this instance cached
        # Class name only: a KV error message can carry the credentialed REST URL.
        log_event("kv_error", op="get", error=type(exc).__name__)
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
    try:
        await kv.command(*creds, "SET", key, value, "EX", str(max(1, int(ttl_seconds))))
    except Exception as exc:  # noqa: BLE001 - a failed write just leaves the local mirror
        log_event("kv_error", op="set", error=type(exc).__name__)


async def _kv_set_nx(memory: InMemoryCache, key: str, value: str, ttl_seconds: float) -> bool:
    """Write only when the key holds nothing (Redis ``SET ... NX``); return
    whether this call wrote.

    The mirror follows what we believe KV holds, as in ``_kv_set``: on a KV
    write it is overwritten with our value; on an NX miss (Upstash answers
    ``null``) KV holds someone else's newer entry, whose value we don't know, so
    the mirror is left as is. Without KV, or when the KV write fails, the mirror
    is the only store we can reason about, so it gets the same only-if-absent
    rule locally.
    """
    creds = kv.credentials()
    if creds is not None:
        try:
            result = await kv.command(
                *creds, "SET", key, value, "EX", str(max(1, int(ttl_seconds))), "NX"
            )
        except Exception as exc:  # noqa: BLE001 - fall through to the local-only rule
            log_event("kv_error", op="set_nx", error=type(exc).__name__)
        else:
            if result is None:
                return False
            memory.set(key, value, ttl_seconds)
            return True
    if memory.get(key) is not None:
        return False
    memory.set(key, value, ttl_seconds)
    return True


async def _cache_read(key: str) -> str | None:
    return await _kv_get(_cache, key)


async def _cache_write(key: str, value: str, ttl_seconds: float) -> None:
    await _kv_set(_cache, key, value, ttl_seconds)


async def _cache_write_if_absent(key: str, value: str, ttl_seconds: float) -> bool:
    return await _kv_set_nx(_cache, key, value, ttl_seconds)


async def _stale_read(key: str) -> str | None:
    return await _kv_get(_stale, _STALE_PREFIX + key)


async def _stale_write(key: str, value: str, ttl_seconds: float) -> None:
    await _kv_set(_stale, _STALE_PREFIX + key, value, ttl_seconds)


def effective_mode() -> str:
    """The mode the service can actually serve right now (never a lie)."""
    return "fixture" if get_settings().fixture_mode else "live"


def cache_size() -> int:
    """Entry count of this instance's response cache (a health-check signal).

    Only the in-memory store is counted: when KV backs the cache this is the
    local mirror, not the shared database.
    """
    return len(_cache)


def _cache_key(profile: ProfileInput) -> str:
    # Scope the key by SCORE_VERSION (scoring engine), deploy env (so a preview
    # deploy can't pollute production), and mode (fixture vs live data must never
    # share an entry). Judge handles are joined in registry order and ALWAYS
    # emitted, even when unset: an omitted segment would let two different inputs
    # collapse onto the same key. Absent handles serialize to "" — not the literal
    # "None" — so an unset handle and a real handle named "None" don't collide.
    settings = get_settings()
    mode = "fixture" if settings.fixture_mode else "live"
    handles = "|".join(profile.handle_for(p.param) or "" for p in JUDGES)
    return f"summary:v{SCORE_VERSION}:{settings.vercel_env}:{mode}:{profile.github}|{handles}"


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


class _Unread(Enum):
    """Sentinel type: the last-good store has not been consulted yet."""

    TOKEN = 0


_UNREAD = _Unread.TOKEN

# A refresh handed back to the route: run it once, after the response is sent.
Refresh = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class SummaryResult:
    """What ``get_summary_stale_first`` answers with.

    ``refresh`` is set only when ``summary`` is a stale last-good copy served in
    place of a live build. The caller must schedule it to run after the
    response body is sent (the routes use the response's ``BackgroundTask``);
    it never raises, and dropping it is safe (the claim it holds expires).
    """

    summary: CodemaruSummary
    refresh: Refresh | None = None


async def _read_cached(key: str, profile: ProfileInput) -> tuple[CodemaruSummary | None, str]:
    """Look the profile up in the response cache.

    Returns the cached summary (or None) and the miss kind for the cache log
    line: "rebuild" distinguishes a cached entry we had to throw away (schema
    drift from another deploy) from a plain "miss" — a spike in one is a bug,
    the other is just cold traffic.
    """
    cached = await _cache_read(key)
    if cached is None:
        return None, "miss"
    restored = _load_summary(cached)
    if restored is None:
        # Incompatible/corrupt entry — the rebuild that follows overwrites it.
        return None, "rebuild"
    log_event("cache", result="hit", handle=profile.github, stale=restored.stale)
    return restored, "hit"


async def get_summary(profile: ProfileInput) -> CodemaruSummary:
    """Return the summary for a profile, using the cache when warm.

    A miss is always rebuilt before returning (see the module docstring for the
    stale-first variant the web routes use).
    """
    settings = get_settings()
    key = _cache_key(profile)
    cached, result = await _read_cached(key, profile)
    if cached is not None:
        return cached
    return await _build_and_store(key, profile, settings, result=result)


async def get_summary_stale_first(profile: ProfileInput) -> SummaryResult:
    """Return a summary without waiting on a live build when a last-good copy exists.

    Live mode, response-cache miss: read the last-good store (one more KV read,
    bounded by ``kv_timeout_seconds``). If it holds a summary, answer with it
    right away — marked ``stale`` so the footer and JSON say so, and so it only
    earns the short negative TTL at both caches — and hand the live rebuild back
    as ``SummaryResult.refresh``. The rebuild then writes the response cache and
    the last-good store exactly as the synchronous path does.

    Without a last-good entry (the first request ever for this profile, or it
    aged out of ``stale_ttl_seconds``) there is nothing to serve, so the build
    runs synchronously as before. Fixture mode never goes stale-first: its
    build is instant and deterministic.

    Hot path cost before responding: the cache read plus, on a miss, the stale
    read. Nothing is written until the refresh runs.
    """
    settings = get_settings()
    key = _cache_key(profile)
    cached, result = await _read_cached(key, profile)
    if cached is not None:
        return SummaryResult(cached)
    if settings.fixture_mode:
        return SummaryResult(await _build_and_store(key, profile, settings, result=result))

    last_good = await _read_last_good(key)
    if last_good is None:
        # Pass the read along so a degraded build doesn't repeat it.
        summary = await _build_and_store(key, profile, settings, result=result, last_good=None)
        return SummaryResult(summary)

    served = last_good.model_copy(update={"stale": True})
    refresh = _claim_refresh(key, profile, settings, last_good)
    log_event(
        "cache",
        result="stale_first",
        handle=profile.github,
        stale=True,
        refreshing=refresh is not None,
    )
    return SummaryResult(served, refresh)


def _refresh_claim_seconds(settings: Settings) -> float:
    """How long a refresh claim blocks another one on this instance.

    The refresh's own worst case is one KV write (the stale copy), the build
    budget, a stale read, then the final writes — so a claim older than that
    plus a margin belongs to a refresh that will never release it.
    """
    return (
        settings.card_build_timeout_seconds
        + 3 * settings.kv_timeout_seconds
        + _REFRESH_CLAIM_MARGIN
    )


def _claim_refresh(
    key: str, profile: ProfileInput, settings: Settings, last_good: CodemaruSummary
) -> Refresh | None:
    """Claim the background refresh for ``key`` on this instance.

    Returns the refresh coroutine function, or None when another request on
    this instance already holds a live claim. The claim is taken *here*, in the
    request path, not when the refresh starts: concurrent requests are all
    served before any BackgroundTask begins, so a claim taken inside the task
    would let every one of them through.
    """
    now = monotonic()
    claimed_at = _refreshing.get(key)
    if claimed_at is not None and now - claimed_at < _refresh_claim_seconds(settings):
        return None
    _refreshing[key] = now

    async def refresh() -> None:
        await _refresh(key, profile, settings, last_good, claimed_at=now)

    return refresh


async def _refresh(
    key: str,
    profile: ProfileInput,
    settings: Settings,
    last_good: CodemaruSummary,
    *,
    claimed_at: float,
) -> None:
    """Rebuild a profile in the background after a stale copy was served.

    Never raises: it runs after the response is sent, where an exception has no
    one to report to (Starlette would only log it, and a second background task
    queued behind it would be skipped). Failures are logged and the stale copy
    simply stays until the next miss retries.
    """
    started = monotonic()
    try:
        # Write the served stale copy to the response cache first (stale ->
        # short negative TTL). This is the cross-instance dedupe: until the
        # fresh result lands, other instances get a cache hit on it instead of
        # a miss that would start another refresh. The write is only-if-absent
        # (SET NX): if another instance's rebuild already landed a fresh entry
        # for this key, this late stale copy must not replace it. Our own fresh
        # result still wins — the build's write after this one is
        # unconditional. It goes to the response cache only: a stale-marked
        # copy must never reach the last-good store.
        stale_copy = last_good.model_copy(update={"stale": True})
        await _cache_write_if_absent(
            key, stale_copy.model_dump_json(), _cache_ttl(stale_copy, settings)
        )
        summary = await _build_and_store(
            key, profile, settings, result="refresh", last_good=last_good
        )
        log_event(
            "refresh",
            handle=profile.github,
            ms=elapsed_ms(started),
            stale=summary.stale,
        )
    except Exception:  # noqa: BLE001 - background work must never raise
        log_exception("refresh_error", handle=profile.github)
    finally:
        # Release only our own claim: if it expired and another request
        # re-claimed the key meanwhile, that newer refresh still owns it.
        if _refreshing.get(key) == claimed_at:
            del _refreshing[key]


async def _build_and_store(
    key: str,
    profile: ProfileInput,
    settings: Settings,
    *,
    result: str,
    last_good: CodemaruSummary | None | _Unread = _UNREAD,
) -> CodemaruSummary:
    """Build a summary now (fixture or live), cache it, and log the outcome.

    ``last_good`` is the already-read last-good summary when the caller has
    consulted the stale store; left unread, a degraded live build reads it
    itself.
    """
    if settings.fixture_mode:
        summary = _build_fixture(profile)
        ttl = await _store(key, summary, settings)
    else:
        summary = await _build_live(profile, settings)
        summary, ttl = await _finalize_live(key, summary, settings, last_good)
    log_event("cache", result=result, handle=profile.github, stale=summary.stale, ttl=ttl)
    return summary


async def _read_last_good(key: str) -> CodemaruSummary | None:
    raw = await _stale_read(key)
    return _load_summary(raw) if raw is not None else None


async def _finalize_live(
    key: str,
    summary: CodemaruSummary,
    settings: Settings,
    last_good: CodemaruSummary | None | _Unread,
) -> tuple[CodemaruSummary, int]:
    """Apply stale fallback to a fresh live build and cache the outcome.

    On a fully-successful build, refresh the last-good store; on a degraded
    build, fall back to the last good summary if one is still retained. This
    keeps a user's card intact through a transient platform outage instead of
    showing a suddenly-degraded score for the cache lifetime.

    Returns the summary to serve and the response-cache TTL chosen for it. On
    the success path the two writes run concurrently, so the post-build KV cost
    is one ``kv_timeout_seconds`` either way (see the budget in settings.py).
    """
    # `not summary.stale` is defensive: a fresh build is never stale, and a
    # stale copy written here would keep re-serving itself as "last good".
    if summary.overall_status is PlatformStatus.OK and not summary.stale:
        ttl = _cache_ttl(summary, settings)
        payload = summary.model_dump_json()
        await asyncio.gather(
            _stale_write(key, payload, settings.stale_ttl_seconds),
            _cache_write(key, payload, ttl),
        )
        return summary, ttl
    if isinstance(last_good, _Unread):
        last_good = await _read_last_good(key)
    if last_good is not None:
        # Serve the last good summary, but mark it stale so JSON consumers and
        # the card footer can tell it isn't a fresh read.
        summary = last_good.model_copy(update={"stale": True})
    return summary, await _store(key, summary, settings)


async def _store(key: str, summary: CodemaruSummary, settings: Settings) -> int:
    """Cache the summary and return the TTL that was chosen for it.

    The field-name form is stored so it round-trips back through validation; the
    JSON endpoint serializes with aliases separately for the public response.
    """
    ttl = _cache_ttl(summary, settings)
    await _cache_write(key, summary.model_dump_json(), ttl)
    return ttl


def _cache_ttl(summary: CodemaruSummary, settings: Settings) -> int:
    """How long this summary may be cached.

    A missing GitHub user is a stable answer, not a blip: retrying it every
    minute only burns GraphQL quota, so it gets its own longer TTL. The note is
    matched (rather than the fetch re-run) against the adapter's own constant, so
    only a real "no such user" qualifies — an HTTP failure there is noted as
    ``http <status>`` and must not pin an outage on every handle. Everything
    else degraded — a failed platform, or a stale-fallback copy (whose
    ``overall_status`` is the *restored* OK, so ``stale`` is what gives it away)
    — gets the short negative TTL, so a transient failure isn't pinned for the
    full cache lifetime.
    """
    github = summary.snapshots.github
    if (
        github is not None
        and github.status is PlatformStatus.UNAVAILABLE
        and github.note == _GITHUB_NOT_FOUND_NOTE
    ):
        return settings.not_found_cache_ttl_seconds
    if summary.stale or summary.overall_status is not PlatformStatus.OK:
        return settings.negative_cache_ttl_seconds
    return settings.cache_ttl_seconds


def _build_fixture(profile: ProfileInput) -> CodemaruSummary:
    bundle = resolve_fixture_bundle(profile)
    return build_summary(profile, bundle, FIXED_TIMESTAMP)


def _judge_fetchers() -> dict[str, JudgeFetch]:
    """Registry key → adapter, resolved on every call.

    Built here rather than as a module constant so the lookup goes through this
    module's globals at call time — which is what lets tests monkeypatch
    ``service.fetch_solvedac`` / ``service.fetch_leetcode`` and be honoured.

    Every registry key must appear here and in ``_JUDGE_UNAVAILABLE``: a judge
    missing from this map is silently never fetched, and one missing from that
    map raises when the card-build budget cuts its task short.
    """
    return {
        "solvedac": fetch_solvedac,
        "leetcode": fetch_leetcode,
        "jungol": fetch_jungol,
    }


def _assign_judge(bundle: SnapshotBundle, key: str, snapshot: JudgeSnapshot) -> None:
    """Store a judge snapshot on the bundle field named by its registry key."""
    setattr(bundle, key, snapshot)


async def _cancel_unfinished(tasks: Mapping[str, asyncio.Task[Any]]) -> list[str]:
    """Cancel every task without a result, then await its cancellation.

    Returns the keys that were cut short. Tasks that already completed are left
    alone — their data is real and paid for, so the budget only discards what was
    still in flight. Awaiting the cancellations keeps the shared httpx client
    from being closed out from under a live request.

    ``cancelled()`` is checked alongside ``done()``: expiring ``asyncio.timeout``
    cancels *this* coroutine, which propagates into whichever task it happened to
    be awaiting. That task is then done but has no result to read.
    """
    unfinished = [key for key, task in tasks.items() if not task.done() or task.cancelled()]
    for key in unfinished:
        tasks[key].cancel()
    for key in unfinished:
        # The cancellation is the expected outcome; an adapter that raised on its
        # way out is no worse than the timeout we are already reporting.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await tasks[key]
    return unfinished


async def _build_live(profile: ProfileInput, settings: Settings) -> CodemaruSummary:
    """Fetch all requested platforms concurrently and assemble the summary.

    Adapters never raise — each maps failures to an ``unavailable`` snapshot — so
    one platform failing degrades the card instead of breaking the request.

    The whole fetch phase also runs under a single ``card_build_timeout_seconds``
    ceiling. ``adapter_timeout_seconds`` bounds one *request*, but GitHub
    paginates sequentially, so the worst case stacks well past a serverless
    function's limit — and a function killed by the platform returns no error
    card and writes no negative cache entry. On expiry the platforms that
    finished are kept, the rest are cancelled and substituted with
    ``unavailable``, and the summary degrades to partial (with stale fallback
    applying as usual).
    """
    fetched_at = datetime.now(UTC)
    started = monotonic()
    fetchers = _judge_fetchers()
    budget = settings.card_build_timeout_seconds
    # GitHub is the one adapter that can shorten its own work, so it gets a
    # cooperative deadline: it stops requesting repo pages instead of losing
    # everything to a cancellation. The margin leaves room to assemble a summary.
    deadline = started + budget - _BUILD_DEADLINE_MARGIN

    async with build_client(settings.adapter_timeout_seconds) as client:
        # create_task schedules them concurrently; awaiting in turn still runs
        # them in parallel and keeps each result strongly typed.
        gh_task: asyncio.Task[GitHubSnapshot] = asyncio.create_task(
            fetch_github(
                profile.github,
                token=settings.github_token,
                fetched_at=fetched_at,
                client=client,
                deadline=deadline,
            )
        )
        judge_tasks: dict[str, asyncio.Task[JudgeSnapshot]] = {}
        judge_handles: dict[str, str] = {}
        for platform in JUDGES:
            handle = profile.handle_for(platform.param)
            fetch = fetchers.get(platform.key)
            if not handle or fetch is None:
                continue
            # Adapters without a shared client (solved.ac needs its own curl_cffi
            # session, since Cloudflare blocks httpx) take a timeout instead.
            extra = (
                {"client": client}
                if platform.shared_client
                else {"timeout": settings.adapter_timeout_seconds}
            )
            judge_handles[platform.key] = handle
            judge_tasks[platform.key] = asyncio.create_task(
                fetch(handle, fetched_at=fetched_at, **extra)
            )

        tasks: dict[str, asyncio.Task[Any]] = {"github": gh_task, **judge_tasks}
        timed_out: list[str] = []
        try:
            async with asyncio.timeout(budget):
                for task in tasks.values():
                    await task
        except TimeoutError:
            timed_out = await _cancel_unfinished(tasks)

    github = (
        github_unavailable(profile.github, _BUDGET_NOTE, fetched_at)
        if "github" in timed_out
        else gh_task.result()
    )
    bundle = SnapshotBundle(github=github)
    for key, task in judge_tasks.items():
        snapshot = (
            _JUDGE_UNAVAILABLE[key](judge_handles[key], _BUDGET_NOTE, fetched_at)
            if key in timed_out
            else task.result()
        )
        _assign_judge(bundle, key, snapshot)

    log_event(
        "build",
        handle=profile.github,
        ms=elapsed_ms(started),
        statuses=_platform_statuses(bundle),
        timed_out=timed_out,
    )
    return build_summary(profile, bundle, fetched_at)


def _platform_statuses(bundle: SnapshotBundle) -> dict[str, PlatformStatus]:
    """Per-platform outcome of one build, keyed as the bundle keys them."""
    statuses: dict[str, PlatformStatus] = {}
    if bundle.github is not None:
        statuses["github"] = bundle.github.status
    for platform in JUDGES:
        snapshot = bundle.judge_snapshot(platform.key)
        if snapshot is not None:
            statuses[platform.key] = snapshot.status
    return statuses


def clear_cache() -> None:
    """Drop all cached and last-successful summaries and refresh claims (tests)."""
    _cache.clear()
    _stale.clear()
    _refreshing.clear()
