"""JudgeView construction and the SnapshotBundle judge accessors."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codemaru.fixtures.demo import (
    github_fixture,
    jungol_fixture,
    leetcode_fixture,
    solvedac_fixture,
)
from codemaru.models.snapshot import (
    DifficultyDistribution,
    JudgeView,
    LeetCodeSnapshot,
    LeetCodeSolved,
    PlatformStatus,
    SnapshotBundle,
    SolvedAcSnapshot,
)

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def test_solvedac_judge_view_fields():
    view = solvedac_fixture().judge_view()
    assert view.platform == "solvedac"
    assert view.handle == "codemaru_demo"
    assert view.status is PlatformStatus.OK
    assert view.solved_count == 3100
    # tier 26 of 30 -> 86.7 on the 0-100 scale.
    assert view.rating_evidence == 86.7
    # gold*0.3 + platinum*1 + diamond*2 + ruby*3
    assert view.hard_volume == 940 * 0.3 + 720 + 380 * 2 + 140 * 3


def test_leetcode_judge_view_fields():
    view = leetcode_fixture().judge_view()
    assert view.platform == "leetcode"
    assert view.handle == "codemaru_demo"
    assert view.solved_count == 320 + 640 + 260  # easy + medium + hard
    assert view.hard_volume == 260
    assert view.rating_evidence is not None


def test_jungol_judge_view_scales_the_rating_evidence_by_080():
    view = jungol_fixture().judge_view()
    assert view.platform == "jungol"
    assert view.handle == "codemaru_demo"
    assert view.solved_count == 420
    # tier 14 of 30 -> 46.7, scaled by 0.80 because JungOl's problem pool is far
    # smaller than BOJ's, so the same tier is weaker evidence.
    assert view.rating_evidence == pytest.approx(46.7 * 0.80)
    # Same hard-volume weights as solved.ac: the bands are the same 0..30 scale.
    assert view.hard_volume == 110 * 0.3 + 40 + 10 * 2


def test_jungol_evidence_never_exceeds_solvedac_at_the_same_tier():
    # The scale-down is what keeps a JungOl-only card from reading as deep as an
    # equivalent BOJ one; _algo_depth's max() is what keeps it from lowering
    # anyone who has both.
    same_tier = solvedac_fixture().model_copy(update={"tier": 14})
    jungol_evidence = jungol_fixture().judge_view().rating_evidence
    solvedac_evidence = same_tier.judge_view().rating_evidence
    assert jungol_evidence is not None and solvedac_evidence is not None
    assert jungol_evidence < solvedac_evidence


def test_jungol_unrated_account_reports_zero_rating_evidence():
    # tier 0 means Unrated, a real value — not a missing signal, so it is 0.0
    # rather than None (the same rule solved.ac follows).
    unrated = jungol_fixture().model_copy(
        update={"tier": 0, "rating": 0, "rank": 0, "difficulty": DifficultyDistribution()}
    )
    view = unrated.judge_view()
    assert view.rating_evidence == 0.0
    assert view.hard_volume == 0.0


def test_leetcode_rating_evidence_is_none_without_a_contest_rating():
    # An unrated account reports no rating at all, which must not read as
    # "rated, and bad" — that would drag the Depth axis down.
    unrated = leetcode_fixture().model_copy(update={"contest_rating": None})
    assert unrated.judge_view().rating_evidence is None
    zero = leetcode_fixture().model_copy(update={"contest_rating": 0})
    assert zero.judge_view().rating_evidence is None


def test_solvedac_unrated_still_reports_zero_rating_evidence():
    # solved.ac tier 0 is a real (Unrated) value, not a missing signal.
    unrated = solvedac_fixture().model_copy(
        update={"tier": 0, "difficulty": DifficultyDistribution()}
    )
    view = unrated.judge_view()
    assert view.rating_evidence == 0.0
    assert view.hard_volume == 0.0


def test_judge_view_usable_follows_snapshot_status():
    for status, expected in (
        (PlatformStatus.OK, True),
        (PlatformStatus.PARTIAL, True),
        (PlatformStatus.UNAVAILABLE, False),
    ):
        view = solvedac_fixture().model_copy(update={"status": status}).judge_view()
        assert view.usable is expected


def test_judge_view_is_frozen():
    import dataclasses

    import pytest

    view = solvedac_fixture().judge_view()
    assert isinstance(view, JudgeView)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.solved_count = 0  # type: ignore[misc]


def test_judges_returns_registry_order():
    bundle = SnapshotBundle(
        github=github_fixture(),
        jungol=jungol_fixture(),
        leetcode=leetcode_fixture(),
        solvedac=solvedac_fixture(),
    )
    # Constructed jungol-first, but registry order wins.
    assert [v.platform for v in bundle.judges()] == ["solvedac", "leetcode", "jungol"]


def test_judges_skips_absent_platforms_and_excludes_github():
    assert SnapshotBundle(github=github_fixture()).judges() == []
    only_lc = SnapshotBundle(github=github_fixture(), leetcode=leetcode_fixture())
    assert [v.platform for v in only_lc.judges()] == ["leetcode"]


def test_judges_includes_unavailable_snapshots_as_unusable_views():
    # Present-but-failed judges still appear (confidence and the worst-status
    # roll-up need to see them); `usable` is what gates scoring.
    dead = SolvedAcSnapshot(
        status=PlatformStatus.UNAVAILABLE,
        fetched_at=_TS,
        handle="baek",
        tier=0,
        rating=0,
        solved_count=0,
        class_level=0,
    )
    views = SnapshotBundle(solvedac=dead).judges()
    assert len(views) == 1
    assert views[0].usable is False


def test_judge_snapshot_lookup_by_registry_key():
    bundle = SnapshotBundle(
        github=github_fixture(), solvedac=solvedac_fixture(), jungol=jungol_fixture()
    )
    assert bundle.judge_snapshot("solvedac") is bundle.solvedac
    assert bundle.judge_snapshot("jungol") is bundle.jungol
    assert bundle.judge_snapshot("leetcode") is None
    # GitHub is the identity platform, not a judge.
    assert bundle.judge_snapshot("github") is None
    assert bundle.judge_snapshot("nope") is None


def test_empty_leetcode_solved_view():
    empty = LeetCodeSnapshot(status=PlatformStatus.OK, fetched_at=_TS, username="lc")
    view = empty.judge_view()
    assert view.solved_count == 0
    assert view.hard_volume == 0
    assert view.rating_evidence is None
    assert LeetCodeSolved().hard == 0
