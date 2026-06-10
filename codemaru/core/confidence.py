"""Confidence reflects how complete and trustworthy the underlying data is.

It is deliberately separate from the score and is NOT shown on the card, but it
caps the maximum attainable tier (see tier.py) so sparse or degraded profiles
cannot reach the top tiers. It stays in ``/api/summary.json`` for transparency.
"""

from __future__ import annotations

from codemaru.core.normalization import clamp, log_score, weighted_average
from codemaru.models.snapshot import (
    GitHubSnapshot,
    LeetCodeSnapshot,
    PlatformStatus,
    SnapshotBundle,
    SolvedAcSnapshot,
)

AnySnapshot = GitHubSnapshot | SolvedAcSnapshot | LeetCodeSnapshot


def _status_scale(snapshot: AnySnapshot | None) -> float:
    if snapshot is None:
        return 0.0
    if snapshot.status is PlatformStatus.OK:
        return 1.0
    if snapshot.status is PlatformStatus.PARTIAL:
        return 0.6
    return 0.0


def _github_factor(gh: GitHubSnapshot | None) -> float:
    scale = _status_scale(gh)
    if scale == 0 or gh is None:
        return 0.0
    # Recent-activity evidence (commits/PRs/reviews/active days, past year).
    activity_signal = (
        log_score(
            gh.total_commits + gh.total_pull_requests * 3 + gh.total_reviews * 2 + gh.active_days,
            800,
        )
        / 100
    )
    # A standout owned project is also strong, verifiable evidence — so a
    # historically significant flagship still earns confidence even if recent
    # activity is quiet. Take whichever signal is stronger (never lowers it).
    repo_signal = (
        weighted_average(
            [
                (log_score(gh.top_owned_repo_stars, 20000), 0.75),
                (log_score(gh.top_owned_repo_forks, 5000), 0.25),
            ]
        )
        / 100
    )
    signal = max(activity_signal, repo_signal)
    return scale * (0.35 + 0.65 * signal)


# Per-source trust: how much a judge's data is believed (LeetCode's endpoint is
# unofficial; future scraped judges will be lower still).
_TRUST_SOLVEDAC = 1.0
_TRUST_LEETCODE = 0.75

# A handful of solves carries no real signal, so it adds ~no confidence; the
# curve only ramps up once a profile has a meaningful body of solved problems.
_JUDGE_FREE = 10


def _judge_factor(
    snapshot: AnySnapshot | None, solved: int, *, trust: float, saturation: float
) -> float:
    """Confidence from a judge scaled by *verifiable volume*, not mere presence.

    A near-empty account (e.g. a brand-new LeetCode handle with one solve)
    contributes ~0, so linking it can't inflate the tier; a substantial solve
    history ramps the contribution up. Never negative, so adding a platform
    still can't lower confidence.
    """
    scale = _status_scale(snapshot)
    if scale == 0.0:
        return 0.0
    volume = log_score(max(0, solved - _JUDGE_FREE), saturation) / 100
    return scale * trust * volume


def compute_confidence(bundle: SnapshotBundle) -> float:
    """Return a 0-1 confidence weighted across the available platforms."""
    gh = _github_factor(bundle.github)

    sa = 0.0
    if bundle.solvedac is not None:
        sa = _judge_factor(
            bundle.solvedac, bundle.solvedac.solved_count, trust=_TRUST_SOLVEDAC, saturation=2200
        )

    lc = 0.0
    if bundle.leetcode is not None:
        lc_solved = (
            bundle.leetcode.solved.easy
            + bundle.leetcode.solved.medium
            + bundle.leetcode.solved.hard
        )
        lc = _judge_factor(bundle.leetcode, lc_solved, trust=_TRUST_LEETCODE, saturation=1400)

    confidence = gh * 0.6 + sa * 0.25 + lc * 0.15
    return clamp(round(confidence * 1000) / 1000, 0, 1)
