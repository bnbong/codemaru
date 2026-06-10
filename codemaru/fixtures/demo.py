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
    # The demo is an all-round "Maru" showcase, so every axis reads high.
    return GitHubSnapshot(
        status=PlatformStatus.OK,
        fetched_at=FIXED_TIMESTAMP,
        login="codemaru-demo",
        public_repos=96,
        total_stars=9200,
        total_forks=1600,
        followers=5400,
        total_commits=3600,
        total_pull_requests=420,
        total_issues=210,
        total_reviews=320,
        contributed_repos=82,
        active_days=341,
        longest_streak=126,
        language_count=12,
        top_owned_repo_stars=7400,
        top_owned_repo_forks=1300,
    )


def solvedac_fixture() -> SolvedAcSnapshot:
    return SolvedAcSnapshot(
        status=PlatformStatus.OK,
        fetched_at=FIXED_TIMESTAMP,
        handle="codemaru_demo",
        tier=26,  # Ruby V
        rating=2480,
        solved_count=3100,
        class_level=8,
        difficulty=DifficultyDistribution(
            bronze=300, silver=620, gold=940, platinum=720, diamond=380, ruby=140
        ),
    )


def leetcode_fixture() -> LeetCodeSnapshot:
    return LeetCodeSnapshot(
        status=PlatformStatus.OK,
        fetched_at=FIXED_TIMESTAMP,
        username="codemaru_demo",
        solved=LeetCodeSolved(easy=320, medium=640, hard=260),
        ranking=4210,
        contest_rating=2380,
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
