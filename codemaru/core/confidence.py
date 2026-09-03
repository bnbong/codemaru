"""Confidence reflects how complete and trustworthy the underlying data is.

It is deliberately separate from the score and is NOT shown on the card, but it
caps the maximum attainable tier (see tier.py) so sparse or degraded profiles
cannot reach the top tiers. It stays in ``/api/summary.json`` for transparency.
"""

from __future__ import annotations

from codemaru.adapters.registry import JUDGES
from codemaru.core.normalization import clamp, log_score, weighted_average
from codemaru.models.snapshot import (
    GitHubSnapshot,
    JudgeView,
    PlatformStatus,
    SnapshotBundle,
)


def _status_scale(status: PlatformStatus | None) -> float:
    if status is PlatformStatus.OK:
        return 1.0
    if status is PlatformStatus.PARTIAL:
        return 0.6
    return 0.0


def _github_factor(gh: GitHubSnapshot | None) -> float:
    scale = _status_scale(gh.status if gh is not None else None)
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


# A handful of solves carries no real signal, so it adds ~no confidence; the
# curve only ramps up once a profile has a meaningful body of solved problems.
_JUDGE_FREE = 10

# GitHub is the identity platform and carries the largest single share. Judge
# weights live in the registry (adapters/registry.py) alongside their trust and
# saturation, so adding a judge is one row rather than an edit here.
_GITHUB_WEIGHT = 0.6


def _judge_factor(view: JudgeView, solved: int, *, trust: float, saturation: float) -> float:
    """Confidence from a judge scaled by *verifiable volume*, not mere presence.

    A near-empty account (e.g. a brand-new LeetCode handle with one solve)
    contributes ~0, so linking it can't inflate the tier; a substantial solve
    history ramps the contribution up. Never negative, so adding a platform
    still can't lower confidence.
    """
    scale = _status_scale(view.status)
    if scale == 0.0:
        return 0.0
    volume = log_score(max(0, solved - _JUDGE_FREE), saturation) / 100
    return scale * trust * volume


def compute_confidence(bundle: SnapshotBundle) -> float:
    """Return a 0-1 confidence weighted across the available platforms."""
    total = _github_factor(bundle.github) * _GITHUB_WEIGHT

    # Additive, never renormalized: sharing a fixed budget between judges would
    # LOWER an existing user's confidence the moment a new judge ships. Weights
    # may therefore sum past 1.0 — the clamp below absorbs that, and only a
    # profile maxed out on every axis reaches it.
    for platform in JUDGES:
        snapshot = bundle.judge_snapshot(platform.key)
        if snapshot is None:
            continue
        view = snapshot.judge_view()
        total += platform.weight * _judge_factor(
            view, view.solved_count, trust=platform.trust, saturation=platform.saturation
        )

    return clamp(round(total * 1000) / 1000, 0, 1)
