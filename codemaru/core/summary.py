"""Builds a CodemaruSummary from collected snapshots — the join point between
adapters (snapshots), the scoring engine (scores), and the renderer (metrics +
status). No I/O; fully deterministic."""

from __future__ import annotations

from datetime import datetime

from codemaru.core.format import compact_number, solvedac_tier_name
from codemaru.core.scoring import score_bundle
from codemaru.core.strengths import top_axes
from codemaru.models.input import ProfileInput
from codemaru.models.snapshot import PlatformStatus, SnapshotBundle
from codemaru.models.summary import CodemaruSummary, SupportingMetric


def _worst_status(bundle: SnapshotBundle) -> PlatformStatus:
    statuses = [
        s.status for s in (bundle.github, bundle.solvedac, bundle.leetcode) if s is not None
    ]
    if not statuses:
        return PlatformStatus.UNAVAILABLE
    if PlatformStatus.UNAVAILABLE in statuses or PlatformStatus.PARTIAL in statuses:
        return PlatformStatus.PARTIAL
    return PlatformStatus.OK


def _build_metrics(bundle: SnapshotBundle) -> list[SupportingMetric]:
    metrics: list[SupportingMetric] = []
    gh, sa, lc = bundle.github, bundle.solvedac, bundle.leetcode

    if gh is not None and gh.usable:
        metrics.append(
            SupportingMetric(key="stars", label="Stars", value=compact_number(gh.total_stars))
        )
        metrics.append(
            SupportingMetric(key="commits", label="Commits", value=compact_number(gh.total_commits))
        )
        metrics.append(
            SupportingMetric(key="prs", label="PRs", value=compact_number(gh.total_pull_requests))
        )
    if sa is not None and sa.usable:
        metrics.append(
            SupportingMetric(key="boj", label="BOJ Tier", value=solvedac_tier_name(sa.tier))
        )
        metrics.append(
            SupportingMetric(key="solved", label="Solved", value=compact_number(sa.solved_count))
        )
    if lc is not None and lc.usable:
        total = lc.solved.easy + lc.solved.medium + lc.solved.hard
        metrics.append(SupportingMetric(key="lc", label="LeetCode", value=compact_number(total)))

    return metrics[:6]


def build_summary(
    profile: ProfileInput,
    bundle: SnapshotBundle,
    updated_at: datetime,
) -> CodemaruSummary:
    """Assemble the full summary for one card request."""
    scores = score_bundle(bundle)
    return CodemaruSummary(
        input=profile,
        snapshots=bundle,
        scores=scores,
        strengths=top_axes(scores.axes, 3),
        metrics=_build_metrics(bundle),
        overall_status=_worst_status(bundle),
        updated_at=updated_at,
    )
