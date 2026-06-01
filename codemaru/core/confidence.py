"""Confidence reflects how complete and trustworthy the underlying data is.

It is deliberately separate from the score and is NOT shown on the card, but it
caps the maximum attainable tier (see tier.py) so sparse or degraded profiles
cannot reach the top tiers. It stays in ``/api/summary.json`` for transparency.
"""

from __future__ import annotations

from codemaru.core.normalization import clamp, log_score
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
    volume_signal = (
        log_score(
            gh.total_commits + gh.total_pull_requests * 3 + gh.total_reviews * 2 + gh.active_days,
            800,
        )
        / 100
    )
    return scale * (0.35 + 0.65 * volume_signal)


def compute_confidence(bundle: SnapshotBundle) -> float:
    """Return a 0-1 confidence weighted across the available platforms."""
    gh = _github_factor(bundle.github)
    sa = _status_scale(bundle.solvedac)
    # LeetCode is an unofficial/experimental source, so it is discounted even
    # when the fetch succeeds.
    lc = _status_scale(bundle.leetcode) * 0.7

    confidence = gh * 0.6 + sa * 0.25 + lc * 0.15
    return clamp(round(confidence * 1000) / 1000, 0, 1)
