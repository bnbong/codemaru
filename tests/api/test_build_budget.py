"""The total card-build time budget (live mode).

``adapter_timeout_seconds`` bounds one request; this bounds the whole build. A
serverless function killed by the platform returns no error card and writes no
negative cache entry, so the build must give up on its own terms first.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from codemaru import service
from codemaru.models.input import ProfileInput
from codemaru.models.snapshot import (
    GitHubSnapshot,
    JungOlSnapshot,
    LeetCodeSnapshot,
    LeetCodeSolved,
    PlatformStatus,
    SolvedAcSnapshot,
)

_TS = datetime(2026, 5, 31, tzinfo=UTC)

# Small enough that the budget always wins, large enough that the tasks start.
_TINY_BUDGET = "0.05"

# Vercel's default serverless function timeout — the ceiling the whole request,
# not just the fetch phase, has to stay under.
_FUNCTION_LIMIT = 10.0


def test_the_default_budget_leaves_room_for_the_kv_round_trips_around_it():
    # The budget bounds the FETCH phase only. get_summary brackets it with KV
    # calls — a cache read before, then a stale read/write plus the cache write
    # after — each bounded by kv_timeout_seconds, and a function the platform
    # kills writes no negative cache entry at all (the very thing the budget
    # exists to guarantee). So the sum, not the budget alone, has to fit.
    from codemaru.settings import get_settings

    settings = get_settings()
    kv = settings.kv_timeout_seconds
    worst_case = kv + settings.card_build_timeout_seconds + 2 * kv
    assert worst_case <= _FUNCTION_LIMIT
    # Pinned so lifting the budget back to a value that doesn't fit is deliberate.
    assert settings.card_build_timeout_seconds == 6.0


def _github(login: str) -> GitHubSnapshot:
    return GitHubSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        login=login,
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


async def _ok_github(login: str, **_: Any) -> GitHubSnapshot:
    return _github(login)


async def _ok_leetcode(username: str, **_: Any) -> LeetCodeSnapshot:
    return LeetCodeSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        username=username,
        solved=LeetCodeSolved(easy=100, medium=150, hard=30),
        ranking=50000,
        contest_rating=1700,
    )


async def _never_returns_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
    await asyncio.sleep(3600)
    raise AssertionError("unreachable")  # pragma: no cover


async def _never_returns_jungol(handle: str, **_: Any) -> JungOlSnapshot:
    await asyncio.sleep(3600)
    raise AssertionError("unreachable")  # pragma: no cover


@pytest.fixture
def tiny_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from codemaru.settings import get_settings

    monkeypatch.setenv("CARD_BUILD_TIMEOUT_SECONDS", _TINY_BUDGET)
    get_settings.cache_clear()


async def test_budget_expiry_substitutes_a_timed_out_snapshot(
    live_mode: None, tiny_budget: None, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", _never_returns_solvedac)

    summary = await service.get_summary(ProfileInput(github="octocat", boj="baek"))

    # No exception, and the card still renders — just degraded.
    assert summary.overall_status is PlatformStatus.PARTIAL
    solvedac = summary.snapshots.solvedac
    assert solvedac is not None
    assert solvedac.status is PlatformStatus.UNAVAILABLE
    assert solvedac.note == "timed out (card build budget)"
    assert solvedac.handle == "baek"


async def test_budget_expiry_keeps_the_platforms_that_finished(
    live_mode: None, tiny_budget: None, monkeypatch: pytest.MonkeyPatch
):
    # A slow judge must not cost the user their GitHub data: work already paid
    # for is kept, only what was still in flight is discarded.
    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_leetcode", _ok_leetcode)
    monkeypatch.setattr(service, "fetch_solvedac", _never_returns_solvedac)

    summary = await service.get_summary(ProfileInput(github="octocat", boj="baek", leetcode="lc"))

    github = summary.snapshots.github
    leetcode = summary.snapshots.leetcode
    assert github is not None and github.status is PlatformStatus.OK
    assert github.total_stars == 500
    assert leetcode is not None and leetcode.status is PlatformStatus.OK
    assert leetcode.solved.medium == 150


async def test_budget_expiry_can_time_out_github_itself(
    live_mode: None, tiny_budget: None, monkeypatch: pytest.MonkeyPatch
):
    async def slow_github(login: str, **_: Any) -> GitHubSnapshot:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr(service, "fetch_github", slow_github)

    summary = await service.get_summary(ProfileInput(github="octocat"))

    github = summary.snapshots.github
    assert github is not None
    assert github.status is PlatformStatus.UNAVAILABLE
    assert github.note == "timed out (card build budget)"
    assert github.login == "octocat"


async def test_budget_expiry_gets_the_negative_cache_ttl(
    live_mode: None, tiny_budget: None, monkeypatch: pytest.MonkeyPatch
):
    # The point of degrading on our own terms: a killed function writes nothing,
    # so the next request re-does the same doomed work.
    from codemaru.settings import get_settings

    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", _never_returns_solvedac)
    ttls: list[float] = []

    async def spy(key: str, value: str, ttl_seconds: float) -> None:
        ttls.append(ttl_seconds)

    monkeypatch.setattr(service, "_cache_write", spy)
    service.clear_cache()

    await service.get_summary(ProfileInput(github="octocat", boj="baek"))

    assert ttls == [get_settings().negative_cache_ttl_seconds]


async def test_cancelled_tasks_are_awaited_not_left_dangling(
    live_mode: None, tiny_budget: None, monkeypatch: pytest.MonkeyPatch
):
    # The shared httpx client is closed right after the budget block; leaving a
    # request in flight would tear it down underneath a live connection.
    cancelled = asyncio.Event()

    async def slow_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", slow_solvedac)

    await service.get_summary(ProfileInput(github="octocat", boj="baek"))

    assert cancelled.is_set()


async def test_a_build_inside_the_budget_is_untouched(
    live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    # The default budget never fires for adapters that answer promptly.
    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_leetcode", _ok_leetcode)

    summary = await service.get_summary(ProfileInput(github="octocat", leetcode="lc"))

    assert summary.overall_status is PlatformStatus.OK
    assert summary.snapshots.leetcode is not None
    assert summary.snapshots.leetcode.note is None


async def test_budget_expiry_substitutes_a_timed_out_jungol_snapshot(
    live_mode: None, tiny_budget: None, monkeypatch: pytest.MonkeyPatch
):
    # Every judge needs an entry in service._JUDGE_UNAVAILABLE; without one this
    # path raises KeyError instead of degrading.
    monkeypatch.setattr(service, "fetch_github", _ok_github)
    monkeypatch.setattr(service, "fetch_jungol", _never_returns_jungol)

    summary = await service.get_summary(ProfileInput(github="octocat", jungol="jo"))

    assert summary.overall_status is PlatformStatus.PARTIAL
    jungol = summary.snapshots.jungol
    assert jungol is not None
    assert jungol.status is PlatformStatus.UNAVAILABLE
    assert jungol.note == "timed out (card build budget)"
    assert jungol.handle == "jo"
    # The GitHub data that did arrive is kept.
    assert summary.snapshots.github is not None
    assert summary.snapshots.github.status is PlatformStatus.OK


async def test_every_registry_judge_can_be_budget_cut(
    live_mode: None, tiny_budget: None, monkeypatch: pytest.MonkeyPatch
):
    # Same guarantee as above, but stated over the registry so the next judge
    # added can't quietly skip it.
    from codemaru.adapters.registry import JUDGES

    monkeypatch.setattr(service, "fetch_github", _ok_github)
    for platform in JUDGES:
        monkeypatch.setattr(service, f"fetch_{platform.key}", _never_returns_jungol)

    handles = {p.param: "handle" for p in JUDGES}
    summary = await service.get_summary(ProfileInput(github="octocat", **handles))

    for platform in JUDGES:
        snapshot = summary.snapshots.judge_snapshot(platform.key)
        assert snapshot is not None, platform.key
        assert snapshot.status is PlatformStatus.UNAVAILABLE
        assert snapshot.note == "timed out (card build budget)"
