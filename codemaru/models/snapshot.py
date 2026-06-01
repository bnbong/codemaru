"""Per-platform snapshot models — the raw data each adapter produces.

Every snapshot carries a ``status`` so one platform failing degrades gracefully
instead of breaking the whole card.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class PlatformStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class _SnapshotBase(BaseModel):
    status: PlatformStatus
    fetched_at: datetime = Field(serialization_alias="fetchedAt")
    note: str | None = None

    model_config = {"populate_by_name": True}

    @property
    def usable(self) -> bool:
        """Whether the snapshot carries data worth scoring."""
        return self.status is not PlatformStatus.UNAVAILABLE


class GitHubSnapshot(_SnapshotBase):
    source: Literal["github"] = "github"
    login: str
    public_repos: int = Field(ge=0, serialization_alias="publicRepos")
    total_stars: int = Field(ge=0, serialization_alias="totalStars")
    total_forks: int = Field(ge=0, serialization_alias="totalForks")
    followers: int = Field(ge=0)
    total_commits: int = Field(ge=0, serialization_alias="totalCommits")
    total_pull_requests: int = Field(ge=0, serialization_alias="totalPullRequests")
    total_issues: int = Field(ge=0, serialization_alias="totalIssues")
    total_reviews: int = Field(ge=0, serialization_alias="totalReviews")
    contributed_repos: int = Field(ge=0, serialization_alias="contributedRepos")
    active_days: int = Field(ge=0, serialization_alias="activeDays")
    longest_streak: int = Field(ge=0, serialization_alias="longestStreak")
    language_count: int = Field(ge=0, serialization_alias="languageCount")


class DifficultyDistribution(BaseModel):
    bronze: int = Field(default=0, ge=0)
    silver: int = Field(default=0, ge=0)
    gold: int = Field(default=0, ge=0)
    platinum: int = Field(default=0, ge=0)
    diamond: int = Field(default=0, ge=0)
    ruby: int = Field(default=0, ge=0)


class SolvedAcSnapshot(_SnapshotBase):
    source: Literal["solvedac"] = "solvedac"
    handle: str
    # solved.ac numeric tier: 0 = Unrated, 1..30 = Bronze V .. Ruby I.
    tier: int = Field(ge=0, le=30)
    rating: int = Field(ge=0)
    solved_count: int = Field(ge=0, serialization_alias="solvedCount")
    class_level: int = Field(ge=0, serialization_alias="class")
    difficulty: DifficultyDistribution = Field(default_factory=DifficultyDistribution)


class LeetCodeSolved(BaseModel):
    easy: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    hard: int = Field(default=0, ge=0)


class LeetCodeSnapshot(_SnapshotBase):
    source: Literal["leetcode"] = "leetcode"
    username: str
    solved: LeetCodeSolved = Field(default_factory=LeetCodeSolved)
    ranking: int = Field(default=0, ge=0)
    contest_rating: int | None = Field(default=None, serialization_alias="contestRating")


class SnapshotBundle(BaseModel):
    """All collected snapshots for one card request."""

    github: GitHubSnapshot | None = None
    solvedac: SolvedAcSnapshot | None = None
    leetcode: LeetCodeSnapshot | None = None
