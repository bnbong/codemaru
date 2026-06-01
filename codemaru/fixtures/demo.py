"""Sample fixtures used for dev rendering and deterministic tests.

These let a card render without any secrets or live API calls. Timestamps are
fixed constants so golden tests stay stable.
"""

from __future__ import annotations

from datetime import UTC, datetime

from codemaru.models.input import ProfileInput
from codemaru.models.snapshot import (
    DifficultyDistribution,
    GitHubSnapshot,
    LeetCodeSnapshot,
    LeetCodeSolved,
    PlatformStatus,
    SnapshotBundle,
    SolvedAcSnapshot,
)

FIXED_TIMESTAMP = datetime(2026, 5, 31, tzinfo=UTC)


def github_fixture() -> GitHubSnapshot:
    return GitHubSnapshot(
        status=PlatformStatus.OK,
        fetched_at=FIXED_TIMESTAMP,
        login="codemaru-demo",
        public_repos=42,
        total_stars=1280,
        total_forks=210,
        followers=340,
        total_commits=1850,
        total_pull_requests=164,
        total_issues=98,
        total_reviews=120,
        contributed_repos=37,
        active_days=268,
        longest_streak=54,
        language_count=8,
    )


def solvedac_fixture() -> SolvedAcSnapshot:
    return SolvedAcSnapshot(
        status=PlatformStatus.OK,
        fetched_at=FIXED_TIMESTAMP,
        handle="codemaru_demo",
        tier=18,  # Platinum III
        rating=1640,
        solved_count=1420,
        class_level=6,
        difficulty=DifficultyDistribution(
            bronze=180, silver=420, gold=540, platinum=220, diamond=52, ruby=8
        ),
    )


def leetcode_fixture() -> LeetCodeSnapshot:
    return LeetCodeSnapshot(
        status=PlatformStatus.OK,
        fetched_at=FIXED_TIMESTAMP,
        username="codemaru_demo",
        solved=LeetCodeSolved(easy=210, medium=380, hard=96),
        ranking=84210,
        contest_rating=1872,
    )


def full_bundle() -> SnapshotBundle:
    return SnapshotBundle(
        github=github_fixture(),
        solvedac=solvedac_fixture(),
        leetcode=leetcode_fixture(),
    )


DEMO_INPUT = ProfileInput(github="codemaru-demo", boj="codemaru_demo", leetcode="codemaru_demo")


def resolve_fixture_bundle(profile: ProfileInput) -> SnapshotBundle:
    """Build a fixture bundle personalized with the requested handles.

    The requested handles drive identity and which platforms appear; the metric
    values themselves stay at the fixture sample values. Real adapters replace
    this in a later PR.
    """
    bundle = SnapshotBundle(github=github_fixture().model_copy(update={"login": profile.github}))
    if profile.boj:
        bundle.solvedac = solvedac_fixture().model_copy(update={"handle": profile.boj})
    if profile.leetcode:
        bundle.leetcode = leetcode_fixture().model_copy(update={"username": profile.leetcode})
    return bundle
