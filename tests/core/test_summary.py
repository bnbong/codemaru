"""Tests for card metric assembly in codemaru.core.summary."""

from __future__ import annotations

from codemaru.core.format import compact_number
from codemaru.core.summary import build_summary
from codemaru.fixtures.demo import (
    DEMO_INPUT,
    FIXED_TIMESTAMP,
    full_bundle,
    github_fixture,
    leetcode_fixture,
)
from codemaru.models.snapshot import SnapshotBundle


def _metric_keys(summary):
    return {m.key for m in summary.metrics}


def test_card_has_no_standalone_leetcode_metric():
    summary = build_summary(DEMO_INPUT, full_bundle(), FIXED_TIMESTAMP)
    assert "lc" not in _metric_keys(summary)
    assert all(m.label != "LeetCode" for m in summary.metrics)


def test_solved_metric_combines_all_judges():
    bundle = full_bundle()  # github + solved.ac + leetcode
    summary = build_summary(DEMO_INPUT, bundle, FIXED_TIMESTAMP)
    solved = next(m for m in summary.metrics if m.key == "solved")
    lc = bundle.leetcode
    expected = bundle.solvedac.solved_count + lc.solved.easy + lc.solved.medium + lc.solved.hard
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
