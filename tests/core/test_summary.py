"""Tests for card metric assembly in codemaru.core.summary."""

from __future__ import annotations

from codemaru.core.format import compact_number
from codemaru.core.summary import build_summary
from codemaru.fixtures.demo import (
    DEMO_INPUT,
    FIXED_TIMESTAMP,
    full_bundle,
    github_fixture,
    jungol_fixture,
    leetcode_fixture,
    solvedac_fixture,
)
from codemaru.models.snapshot import PlatformStatus, SnapshotBundle


def _metric_keys(summary):
    return {m.key for m in summary.metrics}


def test_card_has_no_standalone_leetcode_metric():
    summary = build_summary(DEMO_INPUT, full_bundle(), FIXED_TIMESTAMP)
    assert "lc" not in _metric_keys(summary)
    assert all(m.label != "LeetCode" for m in summary.metrics)


def test_solved_metric_combines_all_judges():
    # Derived from judges() rather than a hand-written sum, so adding a judge to
    # the registry can't silently leave this assertion covering a subset.
    bundle = full_bundle()
    summary = build_summary(DEMO_INPUT, bundle, FIXED_TIMESTAMP)
    solved = next(m for m in summary.metrics if m.key == "solved")
    expected = sum(j.solved_count for j in bundle.judges() if j.usable)
    assert solved.value == compact_number(expected)


def test_solved_metric_shown_for_leetcode_only_profile():
    # No BOJ, but LeetCode present -> Solved (combined) still appears; no BOJ Tier.
    bundle = SnapshotBundle(github=github_fixture(), leetcode=leetcode_fixture())
    summary = build_summary(DEMO_INPUT, bundle, FIXED_TIMESTAMP)
    keys = _metric_keys(summary)
    assert "solved" in keys
    assert "boj" not in keys
    lc = bundle.leetcode
    solved = next(m for m in summary.metrics if m.key == "solved")
    assert solved.value == compact_number(lc.solved.easy + lc.solved.medium + lc.solved.hard)


def test_no_solved_metric_without_any_judge():
    summary = build_summary(DEMO_INPUT, SnapshotBundle(github=github_fixture()), FIXED_TIMESTAMP)
    assert "solved" not in _metric_keys(summary)


def _metric(summary, key):
    return next((m for m in summary.metrics if m.key == key), None)


def test_solved_metric_includes_jungol_in_the_total():
    bundle = full_bundle()  # github + solved.ac + leetcode + jungol
    summary = build_summary(DEMO_INPUT, bundle, FIXED_TIMESTAMP)
    lc, sa, jo = bundle.leetcode, bundle.solvedac, bundle.jungol
    expected = (
        sa.solved_count + lc.solved.easy + lc.solved.medium + lc.solved.hard + jo.solved_count
    )
    assert _metric(summary, "solved").value == compact_number(expected)


def test_boj_tier_wins_the_tier_slot_when_both_judges_are_present():
    # Tier names mean different things on different judges, so exactly one row
    # is shown — and solved.ac is the one Korean developers read fastest.
    summary = build_summary(DEMO_INPUT, full_bundle(), FIXED_TIMESTAMP)
    assert _metric(summary, "boj").label == "BOJ Tier"
    assert _metric(summary, "jungol") is None


def test_jungol_takes_the_tier_slot_when_solvedac_is_absent():
    bundle = SnapshotBundle(github=github_fixture(), jungol=jungol_fixture())
    summary = build_summary(DEMO_INPUT, bundle, FIXED_TIMESTAMP)
    jungol = _metric(summary, "jungol")
    assert jungol is not None
    assert jungol.label == "JungOl Tier"
    assert jungol.value == "Gold II"  # tier 14 on the shared solved.ac scale
    assert _metric(summary, "boj") is None


def test_jungol_takes_the_tier_slot_when_solvedac_is_unavailable():
    # A failed solved.ac fetch shouldn't leave the card with no tier row at all.
    dead = solvedac_fixture().model_copy(update={"status": PlatformStatus.UNAVAILABLE})
    bundle = SnapshotBundle(github=github_fixture(), solvedac=dead, jungol=jungol_fixture())
    summary = build_summary(DEMO_INPUT, bundle, FIXED_TIMESTAMP)
    assert _metric(summary, "jungol") is not None
    assert _metric(summary, "boj") is None


def test_no_tier_row_when_jungol_itself_is_unavailable():
    dead = jungol_fixture().model_copy(update={"status": PlatformStatus.UNAVAILABLE})
    bundle = SnapshotBundle(github=github_fixture(), jungol=dead)
    summary = build_summary(DEMO_INPUT, bundle, FIXED_TIMESTAMP)
    assert _metric(summary, "jungol") is None
    assert _metric(summary, "boj") is None


def test_metrics_stay_within_the_six_row_cap():
    summary = build_summary(DEMO_INPUT, full_bundle(), FIXED_TIMESTAMP)
    assert len(summary.metrics) <= 6
