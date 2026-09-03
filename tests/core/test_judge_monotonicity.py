"""The fairness invariant the registry refactor must preserve.

Linking one more usable judge is additive everywhere: solved counts are summed,
rating evidence is a max, hard volume is a sum, and confidence weights are never
renormalized. So adding a judge can never LOWER problem_solving, depth, or
confidence — no matter how empty the new account is. This is what makes it safe
to add a judge to the registry without recalibrating anyone's card.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codemaru.core.confidence import compute_confidence
from codemaru.core.scoring import compute_axis_scores
from codemaru.fixtures.demo import (
    github_fixture,
    jungol_fixture,
    leetcode_fixture,
    solvedac_fixture,
)
from codemaru.models.snapshot import (
    DifficultyDistribution,
    JungOlSnapshot,
    LeetCodeSnapshot,
    LeetCodeSolved,
    PlatformStatus,
    SnapshotBundle,
    SolvedAcSnapshot,
)

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def _leetcode(**overrides: object) -> LeetCodeSnapshot:
    base = LeetCodeSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        username="lc",
        solved=LeetCodeSolved(easy=40, medium=20, hard=5),
        ranking=100000,
        contest_rating=1450,
    )
    return base.model_copy(update=dict(overrides))


def _jungol(**overrides: object) -> JungOlSnapshot:
    base = JungOlSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        handle="jo",
        account_id=54271,
        tier=5,
        rating=180,
        rank=9000,
        solved_count=60,
        difficulty=DifficultyDistribution(bronze=40, silver=15, gold=5),
    )
    return base.model_copy(update=dict(overrides))


def _solvedac(**overrides: object) -> SolvedAcSnapshot:
    base = SolvedAcSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        handle="baek",
        tier=9,
        rating=800,
        solved_count=250,
        class_level=3,
        difficulty=DifficultyDistribution(bronze=120, silver=100, gold=30),
    )
    return base.model_copy(update=dict(overrides))


# Base profiles the extra judge is added on top of.
_BASES: dict[str, SnapshotBundle] = {
    "github_only": SnapshotBundle(github=github_fixture()),
    "github_and_solvedac": SnapshotBundle(github=github_fixture(), solvedac=solvedac_fixture()),
    "solvedac_only": SnapshotBundle(solvedac=solvedac_fixture()),
    "leetcode_only": SnapshotBundle(github=github_fixture(), leetcode=leetcode_fixture()),
    "every_other_judge": SnapshotBundle(
        github=github_fixture(), solvedac=solvedac_fixture(), leetcode=leetcode_fixture()
    ),
    "empty": SnapshotBundle(),
}

# Judges linked on top, from "essentially nothing" to a substantial history.
_ADDED_LEETCODE: dict[str, LeetCodeSnapshot] = {
    "brand_new": _leetcode(solved=LeetCodeSolved(easy=1), contest_rating=None),
    "empty": _leetcode(solved=LeetCodeSolved(), contest_rating=None),
    "modest": _leetcode(),
    "substantial": leetcode_fixture(),
    "partial_status": _leetcode(status=PlatformStatus.PARTIAL),
    "unavailable": _leetcode(status=PlatformStatus.UNAVAILABLE, solved=LeetCodeSolved()),
}


_LEETCODE_FREE_BASES = sorted(name for name, b in _BASES.items() if b.leetcode is None)


@pytest.mark.parametrize("base_name", _LEETCODE_FREE_BASES)
@pytest.mark.parametrize("added_name", sorted(_ADDED_LEETCODE))
def test_adding_a_leetcode_judge_never_lowers_scores(base_name: str, added_name: str):
    base = _BASES[base_name]
    linked = base.model_copy(update={"leetcode": _ADDED_LEETCODE[added_name]})

    before, after = compute_axis_scores(base), compute_axis_scores(linked)
    assert after.problem_solving >= before.problem_solving
    assert after.depth >= before.depth
    assert compute_confidence(linked) >= compute_confidence(base)


@pytest.mark.parametrize(
    "added",
    [
        _solvedac(),
        _solvedac(tier=0, difficulty=DifficultyDistribution()),
        _solvedac(status=PlatformStatus.UNAVAILABLE, solved_count=0),
        solvedac_fixture(),
    ],
    ids=["modest", "unrated", "unavailable", "substantial"],
)
def test_adding_a_solvedac_judge_never_lowers_scores(added: SolvedAcSnapshot):
    base = SnapshotBundle(github=github_fixture(), leetcode=leetcode_fixture())
    linked = base.model_copy(update={"solvedac": added})

    before, after = compute_axis_scores(base), compute_axis_scores(linked)
    assert after.problem_solving >= before.problem_solving
    assert after.depth >= before.depth
    assert compute_confidence(linked) >= compute_confidence(base)


# JungOl accounts skew small (its problem pool is a fraction of BOJ's), so the
# "essentially nothing" end of this range is the realistic case, not an edge one.
_ADDED_JUNGOL: dict[str, JungOlSnapshot] = {
    "brand_new": _jungol(solved_count=1, tier=0, rating=0, rank=0),
    "unranked": _jungol(
        tier=0, rating=0, rank=0, solved_count=0, difficulty=DifficultyDistribution()
    ),
    "modest": _jungol(),
    "substantial": jungol_fixture(),
    "partial_status": _jungol(status=PlatformStatus.PARTIAL),
    "unavailable": _jungol(
        status=PlatformStatus.UNAVAILABLE,
        tier=0,
        rating=0,
        solved_count=0,
        difficulty=DifficultyDistribution(),
    ),
}


@pytest.mark.parametrize("base_name", sorted(_BASES))
@pytest.mark.parametrize("added_name", sorted(_ADDED_JUNGOL))
def test_adding_a_jungol_judge_never_lowers_scores(base_name: str, added_name: str):
    # The whole reason JungOl could ship without recalibrating anyone: its 0.80
    # rating scale feeds a max(), its solves feed a sum, and its confidence
    # weight is added rather than carved out of the others'.
    base = _BASES[base_name]
    linked = base.model_copy(update={"jungol": _ADDED_JUNGOL[added_name]})

    before, after = compute_axis_scores(base), compute_axis_scores(linked)
    assert after.problem_solving >= before.problem_solving
    assert after.depth >= before.depth
    assert compute_confidence(linked) >= compute_confidence(base)


def test_a_strong_jungol_account_cannot_dilute_a_stronger_solvedac_one():
    # rating_evidence is a max across judges, so the 0.80 scale is conservative
    # in one direction only — it never pulls a BOJ-backed Depth down.
    solvedac_only = SnapshotBundle(github=github_fixture(), solvedac=solvedac_fixture())
    with_jungol = solvedac_only.model_copy(update={"jungol": jungol_fixture()})
    assert compute_axis_scores(with_jungol).depth >= compute_axis_scores(solvedac_only).depth


def test_confidence_weights_are_additive_not_renormalized():
    # Sharing a fixed budget between judges would LOWER an existing user's
    # confidence the moment a new judge ships. The weights therefore sum past
    # 1.0 by design, and the [0, 1] clamp absorbs the overshoot.
    from codemaru.adapters.registry import JUDGES
    from codemaru.core.confidence import _GITHUB_WEIGHT

    assert _GITHUB_WEIGHT + sum(p.weight for p in JUDGES) >= 1.0
    assert 0.0 <= compute_confidence(_BASES["github_and_solvedac"]) <= 1.0
