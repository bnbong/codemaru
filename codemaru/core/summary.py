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
    statuses = [bundle.github.status] if bundle.github is not None else []
    statuses += [j.status for j in bundle.judges()]
    if not statuses:
        return PlatformStatus.UNAVAILABLE
    if PlatformStatus.UNAVAILABLE in statuses or PlatformStatus.PARTIAL in statuses:
        return PlatformStatus.PARTIAL
    return PlatformStatus.OK


def _build_metrics(bundle: SnapshotBundle) -> list[SupportingMetric]:
    metrics: list[SupportingMetric] = []
    gh, sa, jo = bundle.github, bundle.solvedac, bundle.jungol

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
    # Exactly one tier row, never two: Bronze/Gold/… mean different things on
    # different judges, so showing two of them side by side reads as a
    # comparison that isn't one. solved.ac wins when it has data (it is the
    # signal Korean developers know best), and JungOl — which uses the same
    # 0..30 scale and the same names — takes the slot only in its absence. The
    # label therefore follows which handles were supplied, not the numbers, so
    # it can't flip between builds.
    if sa is not None and sa.usable:
        metrics.append(
            SupportingMetric(key="boj", label="BOJ Tier", value=solvedac_tier_name(sa.tier))
        )
    elif jo is not None and jo.usable:
        metrics.append(
            SupportingMetric(key="jungol", label="JungOl Tier", value=solvedac_tier_name(jo.tier))
        )

    # "Solved" is the combined problem count across every usable judge — LeetCode,
    # JungOl (and any future judge) fold into this total rather than getting a
    # separate metric, so the card stays platform-agnostic.
    usable_judges = [j for j in bundle.judges() if j.usable]
    if usable_judges:
        solved_total = sum(j.solved_count for j in usable_judges)
        metrics.append(
            SupportingMetric(key="solved", label="Solved", value=compact_number(solved_total))
        )

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
