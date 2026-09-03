"""Status-aware caching and last-successful stale fallback (live mode)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from codemaru import service
from codemaru.adapters.github import NOT_FOUND_NOTE
from codemaru.adapters.github import unavailable_snapshot as github_unavailable
from codemaru.core.scoring import SCORE_VERSION
from codemaru.core.summary import build_summary
from codemaru.models.input import ProfileInput
from codemaru.models.snapshot import (
    GitHubSnapshot,
    PlatformStatus,
    SnapshotBundle,
    SolvedAcSnapshot,
)
from codemaru.settings import get_settings

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def test_cache_key_includes_score_version():
    # Bumping SCORE_VERSION must change the cache key so a formula change can't
    # serve summaries scored by the old engine.
    key = service._cache_key(ProfileInput(github="octocat"))
    assert f"v{SCORE_VERSION}" in key


def _github() -> GitHubSnapshot:
    return GitHubSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        login="octocat",
        public_repos=10,
        total_stars=500,
        total_forks=40,
        followers=80,
        total_commits=900,
        total_pull_requests=70,
        total_issues=30,
        total_reviews=40,
        contributed_repos=12,
        active_days=150,
        longest_streak=20,
        language_count=5,
    )


def _solvedac(status: PlatformStatus) -> SolvedAcSnapshot:
    return SolvedAcSnapshot(
        status=status,
        fetched_at=_TS,
        handle="baek",
        tier=12 if status is PlatformStatus.OK else 0,
        rating=1200 if status is PlatformStatus.OK else 0,
        solved_count=600 if status is PlatformStatus.OK else 0,
        class_level=4 if status is PlatformStatus.OK else 0,
    )


async def _ok_github(login: str, **_: Any) -> GitHubSnapshot:
    return _github()


async def test_stale_fallback_keeps_last_good_through_outage(
    live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    async def ok_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        return _solvedac(PlatformStatus.OK)

    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", ok_solvedac)
    profile = ProfileInput(github="octocat", boj="baek")

    first = await service.get_summary(profile)
    assert first.overall_status is PlatformStatus.OK

    # Simulate the response cache expiring, then solved.ac going down.
    service._cache.clear()

    async def dead_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        return _solvedac(PlatformStatus.UNAVAILABLE)

    monkeypatch.setattr(service, "fetch_solvedac", dead_solvedac)

    second = await service.get_summary(profile)
    # The last good summary is served instead of a suddenly-degraded card, but
    # flagged stale so JSON consumers and the card footer can tell.
    assert second.overall_status is PlatformStatus.OK
    assert first.stale is False
    assert second.stale is True
    assert second.scores == first.scores
    assert second.snapshots == first.snapshots


async def test_degraded_without_prior_success_is_partial(
    live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    async def dead_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        return _solvedac(PlatformStatus.UNAVAILABLE)

    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", dead_solvedac)

    summary = await service.get_summary(ProfileInput(github="octocat", boj="baek"))
    # No prior good summary to fall back to → the partial result is surfaced.
    assert summary.overall_status is PlatformStatus.PARTIAL


# --- negative-cache TTL selection -------------------------------------------


def _record_ttls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture the TTL every _store() hands to the cache writer."""
    ttls: list[float] = []

    async def spy(key: str, value: str, ttl_seconds: float) -> None:
        ttls.append(ttl_seconds)

    monkeypatch.setattr(service, "_cache_write", spy)
    return ttls


async def test_healthy_summary_gets_the_full_ttl(monkeypatch: pytest.MonkeyPatch):
    ttls = _record_ttls(monkeypatch)
    service.clear_cache()

    await service.get_summary(ProfileInput(github="octocat"))

    assert ttls == [get_settings().cache_ttl_seconds]


async def test_degraded_summary_gets_the_negative_ttl(
    live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    async def dead_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        return _solvedac(PlatformStatus.UNAVAILABLE)

    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", dead_solvedac)
    ttls = _record_ttls(monkeypatch)
    service.clear_cache()

    await service.get_summary(ProfileInput(github="octocat", boj="baek"))

    assert ttls == [get_settings().negative_cache_ttl_seconds]


async def test_stale_fallback_is_not_cached_for_the_full_ttl(
    live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    # The stale copy carries the *restored* overall_status (ok), so status alone
    # would have pinned a degraded read behind the full 1h TTL. `stale` is what
    # gives it away.
    async def ok_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        return _solvedac(PlatformStatus.OK)

    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", ok_solvedac)
    profile = ProfileInput(github="octocat", boj="baek")
    await service.get_summary(profile)  # seed the last-good store

    service._cache.clear()

    async def dead_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        return _solvedac(PlatformStatus.UNAVAILABLE)

    monkeypatch.setattr(service, "fetch_solvedac", dead_solvedac)
    ttls = _record_ttls(monkeypatch)

    summary = await service.get_summary(profile)

    assert summary.stale is True
    assert summary.overall_status is PlatformStatus.OK  # restored status
    assert ttls == [get_settings().negative_cache_ttl_seconds]


async def test_missing_github_user_gets_the_longer_not_found_ttl(
    live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    # A handle that doesn't exist is a stable answer, not a blip: re-asking the
    # GraphQL API every 60s would only burn quota.
    async def missing_github(login: str, **_: Any) -> GitHubSnapshot:
        return github_unavailable(login, NOT_FOUND_NOTE, _TS)

    monkeypatch.setattr(service, "fetch_github", missing_github)
    ttls = _record_ttls(monkeypatch)
    service.clear_cache()

    await service.get_summary(ProfileInput(github="ghost-user-404"))

    settings = get_settings()
    assert ttls == [settings.not_found_cache_ttl_seconds]
    assert settings.not_found_cache_ttl_seconds > settings.negative_cache_ttl_seconds


async def test_other_github_failures_keep_the_short_negative_ttl(
    live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    # Only "user not found" earns the long TTL — a transient fetch failure must
    # still be retried quickly.
    async def broken_github(login: str, **_: Any) -> GitHubSnapshot:
        return github_unavailable(login, "request failed", _TS)

    monkeypatch.setattr(service, "fetch_github", broken_github)
    ttls = _record_ttls(monkeypatch)
    service.clear_cache()

    await service.get_summary(ProfileInput(github="octocat"))

    assert ttls == [get_settings().negative_cache_ttl_seconds]


def _ttl_for_github_note(note: str) -> int:
    """TTL the service picks for a summary whose GitHub snapshot carries ``note``."""
    bundle = SnapshotBundle(github=github_unavailable("octocat", note, _TS))
    summary = build_summary(ProfileInput(github="octocat"), bundle, _TS)
    return service._cache_ttl(summary, get_settings())


def test_graphql_rate_limited_note_gets_the_short_negative_ttl():
    # A GraphQL `errors` array (e.g. RATE_LIMITED) alongside a null user is
    # noted `graphql error: RATE_LIMITED` by the adapter, distinct from a real
    # missing user — it must keep the short retry-soon TTL, not the long one.
    settings = get_settings()
    assert (
        _ttl_for_github_note("graphql error: RATE_LIMITED") == settings.negative_cache_ttl_seconds
    )


def test_only_a_real_missing_user_earns_the_long_not_found_ttl():
    # The adapter's classification is what selects the TTL, so the two must be
    # read together: an expired token (401), a rate limit (403) or a GitHub outage
    # (5xx) is noted `http <status>` and retried in a minute. Reporting those as
    # "user not found" — which the adapter used to do for every non-200 — pinned
    # the outage on EVERY handle that asked, for the full 10 minutes.
    settings = get_settings()
    assert _ttl_for_github_note(NOT_FOUND_NOTE) == settings.not_found_cache_ttl_seconds
    for note in ("http 401", "http 403", "http 502", "request failed"):
        assert _ttl_for_github_note(note) == settings.negative_cache_ttl_seconds, note
    assert settings.not_found_cache_ttl_seconds > settings.negative_cache_ttl_seconds
