"""Per-platform snapshot models — the raw data each adapter produces.

Every snapshot carries a ``status`` so one platform failing degrades gracefully
instead of breaking the whole card.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# ``core.normalization`` is a leaf module (stdlib only), so importing it here
# introduces no cycle — unlike the rest of ``core``, which depends on models.
from codemaru.core.normalization import linear_score


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


@dataclass(frozen=True)
class JudgeView:
    """A judge snapshot normalized to the handful of fields scoring cares about.

    A plain dataclass, never a pydantic model: it is a read-only *view* over a
    snapshot and must never reach ``/api/summary.json``, whose ``snapshots``
    object is a public contract keyed by platform. Per-platform formulas live in
    each snapshot's ``judge_view()``, which keeps platform knowledge out of
    ``core/scoring.py``.
    """

    # Registry key ("solvedac", "leetcode", ...).
    platform: str
    handle: str
    status: PlatformStatus
    solved_count: int
    # Rating signal normalized to 0-100, or None when the judge exposes none
    # (an unrated account, or a platform without a rating at all).
    rating_evidence: float | None
    # Difficulty-weighted volume of hard problems, on each platform's own scale.
    hard_volume: float

    @property
    def usable(self) -> bool:
        """Whether the underlying snapshot carries data worth scoring."""
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
    # The single most-starred owned (non-fork) repo — a "representative project"
    # depth signal, distinct from total_stars (reach). Owner-only: an org-owned
    # flagship (e.g. python/cpython) is not captured (public-data limitation).
    top_owned_repo_stars: int = Field(default=0, ge=0, serialization_alias="topOwnedRepoStars")
    top_owned_repo_forks: int = Field(default=0, ge=0, serialization_alias="topOwnedRepoForks")


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

    def judge_view(self) -> JudgeView:
        d = self.difficulty
        return JudgeView(
            platform="solvedac",
            handle=self.handle,
            status=self.status,
            solved_count=self.solved_count,
            rating_evidence=linear_score(self.tier, 30),
            # Gold problems are common enough to count only fractionally; the
            # weights climb steeply so a handful of Ruby solves reads as depth.
            hard_volume=d.gold * 0.3 + d.platinum * 1 + d.diamond * 2 + d.ruby * 3,
        )


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

    def judge_view(self) -> JudgeView:
        # 1200 is LeetCode's starting contest rating, so only the margin above it
        # is evidence. An unrated account reports no rating rather than a zero,
        # which would otherwise read as "rated, and bad".
        rating = self.contest_rating
        evidence = linear_score(rating - 1200, 2000) if rating is not None and rating > 0 else None
        return JudgeView(
            platform="leetcode",
            handle=self.username,
            status=self.status,
            solved_count=self.solved.easy + self.solved.medium + self.solved.hard,
            rating_evidence=evidence,
            hard_volume=self.solved.hard,
        )


# JungOl states on its own account pages that tiers are computed from a
# solved.ac AC rating, so the scales really are the same axis. Its problem pool
# is far smaller than BOJ's, though, so an identical tier is weaker evidence —
# the rating signal is scaled down rather than taken at face value. ``_algo_depth``
# takes the MAX across judges, so this can only ever be conservative: it never
# lowers a card that also has solved.ac data.
JUNGOL_RATING_SCALE = 0.80


class JungOlSnapshot(_SnapshotBase):
    source: Literal["jungol"] = "jungol"
    handle: str
    # JungOl's internal account id, which its handle URL resolves to.
    account_id: int = Field(default=0, ge=0, serialization_alias="accountId")
    # Same 0..30 axis as solved.ac (0 = Unrated).
    tier: int = Field(ge=0, le=30)
    # JungOl calls this "rv" — the AC rating behind the tier.
    rating: int = Field(ge=0)
    # Site-wide rank. Unranked accounts report no rank at all, which lands here
    # as 0 (the same "no data" value solved.ac's unrated tier uses).
    rank: int = Field(default=0, ge=0)
    solved_count: int = Field(ge=0, serialization_alias="solvedCount")
    difficulty: DifficultyDistribution = Field(default_factory=DifficultyDistribution)

    def judge_view(self) -> JudgeView:
        d = self.difficulty
        return JudgeView(
            platform="jungol",
            handle=self.handle,
            status=self.status,
            solved_count=self.solved_count,
            rating_evidence=linear_score(self.tier, 30) * JUNGOL_RATING_SCALE,
            # Identical to solved.ac's weighting: the bands are the same scale,
            # so the same problem difficulty is worth the same depth.
            hard_volume=d.gold * 0.3 + d.platinum * 1 + d.diamond * 2 + d.ruby * 3,
        )


# Every snapshot that is a judge (i.e. everything but GitHub, the identity).
JudgeSnapshot = SolvedAcSnapshot | LeetCodeSnapshot | JungOlSnapshot


class SnapshotBundle(BaseModel):
    """All collected snapshots for one card request."""

    github: GitHubSnapshot | None = None
    solvedac: SolvedAcSnapshot | None = None
    leetcode: LeetCodeSnapshot | None = None
    # Added after the wire format was public, so it is purely additive: existing
    # consumers of ``snapshots.solvedac`` / ``snapshots.leetcode`` are untouched.
    jungol: JungOlSnapshot | None = None

    def judge_snapshot(self, key: str) -> JudgeSnapshot | None:
        """Return the judge snapshot stored under a registry key, if present."""
        snapshot = getattr(self, key, None)
        if isinstance(snapshot, SolvedAcSnapshot | LeetCodeSnapshot | JungOlSnapshot):
            return snapshot
        return None

    def judges(self) -> list[JudgeView]:
        """Normalized views of every judge present, in registry order."""
        # Imported inside the method on purpose: ``codemaru.adapters.__init__``
        # imports the adapter modules, which import this one, so a module-level
        # import would close that cycle. Module lookup is cached after the first
        # call, so the per-call cost is a dict hit.
        from codemaru.adapters.registry import JUDGES

        views: list[JudgeView] = []
        for platform in JUDGES:
            snapshot = self.judge_snapshot(platform.key)
            if snapshot is not None:
                views.append(snapshot.judge_view())
        return views
