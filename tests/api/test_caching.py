"""Status-aware caching and last-successful stale fallback (live mode)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from codemaru import service
from codemaru.core.scoring import SCORE_VERSION
from codemaru.models.input import ProfileInput
from codemaru.models.snapshot import GitHubSnapshot, PlatformStatus, SolvedAcSnapshot

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
