"""Per-axis scoring and the overall blend.

Pure functions: the same snapshot bundle always yields the same scores, which
keeps golden tests stable. Component weights only count when their underlying
snapshot is present, so a GitHub-only user still gets meaningful Open Source /
Impact / Consistency scores.

Bump ``SCORE_VERSION`` whenever any formula here, in confidence.py, or tier.py
changes, and refresh the affected tests.
"""

from __future__ import annotations

from codemaru.core.confidence import compute_confidence
from codemaru.core.normalization import linear_score, log_score, weighted_average
from codemaru.core.tier import compute_tier
from codemaru.models.score import Axis, AxisScores, NormalizedScores
from codemaru.models.snapshot import (
    GitHubSnapshot,
    LeetCodeSnapshot,
    SnapshotBundle,
    SolvedAcSnapshot,
)

SCORE_VERSION = "0.2.0"

# Overall-score axis weights (mirrors the documented formula).
AXIS_WEIGHTS: dict[Axis, float] = {
    Axis.OPEN_SOURCE: 0.30,
    Axis.PROBLEM_SOLVING: 0.20,
    Axis.DEPTH: 0.20,
    Axis.CONSISTENCY: 0.15,
    Axis.IMPACT: 0.15,
}


def _open_source(gh: GitHubSnapshot | None) -> float:
    if gh is None or not gh.usable:
        return 0.0
    return weighted_average(
        [
            (log_score(gh.total_commits, 2000), 0.30),
            (log_score(gh.total_pull_requests, 200), 0.25),
            (log_score(gh.total_reviews, 150), 0.20),
            (log_score(gh.contributed_repos, 60), 0.15),
            (log_score(gh.total_issues, 150), 0.10),
        ]
    )


def _impact(gh: GitHubSnapshot | None) -> float:
    if gh is None or not gh.usable:
        return 0.0
    return weighted_average(
        [
            (log_score(gh.total_stars, 3000), 0.45),
            (log_score(gh.total_forks, 800), 0.20),
            (log_score(gh.followers, 1500), 0.20),
            (log_score(gh.public_repos, 80), 0.15),
        ]
    )


def _consistency(gh: GitHubSnapshot | None) -> float:
    if gh is None or not gh.usable:
        return 0.0
    return weighted_average(
        [
            (linear_score(gh.active_days, 365), 0.60),
            (linear_score(gh.longest_streak, 120), 0.40),
        ]
    )


def _problem_solving(sa: SolvedAcSnapshot | None, lc: LeetCodeSnapshot | None) -> float:
    """Total problems solved across judges, summed then saturated once.

    Counts are SUMMED (not averaged across platforms), so linking another judge
    can only raise the score — a freshly created account with a handful of solves
    never dilutes an established profile. Every solve is worth the same regardless
    of platform; difficulty is handled separately by ``_depth``.
    """
    total = 0
    has_judge = False
    if sa is not None and sa.usable:
        total += sa.solved_count
        has_judge = True
    if lc is not None and lc.usable:
        total += lc.solved.easy + lc.solved.medium + lc.solved.hard
        has_judge = True
    if not has_judge:
        return 0.0
    return log_score(total, 2500)


def _depth(
    gh: GitHubSnapshot | None,
    sa: SolvedAcSnapshot | None,
    lc: LeetCodeSnapshot | None,
) -> float:
    """Problem-solving depth, combined across judges monotonically.

    Rating evidence (BOJ tier vs LeetCode contest) is the BEST across judges
    (max), hard-problem volume is SUMMED, and language breadth is a mild fallback.
    So adding a judge never lowers depth — it can only confirm or raise it.
    """
    components: list[tuple[float, float]] = []

    # Rating evidence: take the strongest available, not the average. Add it only
    # when there is real evidence (> 0); a zero rating would just dilute the rest.
    ratings: list[float] = []
    if sa is not None and sa.usable:
        ratings.append(linear_score(sa.tier, 30))
    if lc is not None and lc.usable and lc.contest_rating is not None and lc.contest_rating > 0:
        ratings.append(linear_score(lc.contest_rating - 1200, 2000))
    if ratings and max(ratings) > 0:
        components.append((max(ratings), 0.35))

    # Hard-problem volume, summed across judges (BOJ is difficulty-weighted).
    # Skipped entirely when there is no hard evidence, so linking a fresh judge
    # with zero hard solves never dilutes an existing depth signal.
    hard = 0.0
    if sa is not None and sa.usable:
        d = sa.difficulty
        hard += d.gold * 0.3 + d.platinum * 1 + d.diamond * 2 + d.ruby * 3
    if lc is not None and lc.usable:
        hard += lc.solved.hard
    if hard > 0:
        components.append((log_score(hard, 400), 0.35))

    if gh is not None and gh.usable:
        # Language breadth is a mild depth signal when no judge data exists.
        components.append((log_score(gh.language_count, 12), 0.10))
    return weighted_average(components)


def compute_axis_scores(bundle: SnapshotBundle) -> AxisScores:
    """Compute all five axis scores from a snapshot bundle."""
    gh, sa, lc = bundle.github, bundle.solvedac, bundle.leetcode
    return AxisScores(
        open_source=_open_source(gh),
        impact=_impact(gh),
        consistency=_consistency(gh),
        problem_solving=_problem_solving(sa, lc),
        depth=_depth(gh, sa, lc),
    )


def score_bundle(bundle: SnapshotBundle) -> NormalizedScores:
    """Produce normalized scores, overall, confidence, and tier for a bundle."""
    axes = compute_axis_scores(bundle)
    overall = weighted_average([(axes.get(axis), weight) for axis, weight in AXIS_WEIGHTS.items()])
    confidence = compute_confidence(bundle)
    tier = compute_tier(overall, confidence)
    return NormalizedScores(
        axes=axes,
        overall=overall,
        confidence=confidence,
        tier=tier,
        score_version=SCORE_VERSION,
    )
