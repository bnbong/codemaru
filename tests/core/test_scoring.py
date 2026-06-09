from codemaru.core.confidence import compute_confidence
from codemaru.core.scoring import SCORE_VERSION, score_bundle
from codemaru.core.strengths import top_axes
from codemaru.core.tier import compute_tier
from codemaru.fixtures.demo import (
    full_bundle,
    github_fixture,
    leetcode_fixture,
    solvedac_fixture,
)
from codemaru.models.score import AXES, TIERS, Axis, AxisScores, Tier
from codemaru.models.snapshot import (
    GitHubSnapshot,
    LeetCodeSolved,
    PlatformStatus,
    SnapshotBundle,
)


def _github_only() -> SnapshotBundle:
    return SnapshotBundle(github=github_fixture())


def test_score_bundle_ranges_and_version():
    scores = score_bundle(full_bundle())
    for axis in AXES:
        assert 0 <= scores.axes.get(axis) <= 100
    assert 0 <= scores.overall <= 100
    assert 0 < scores.confidence <= 1
    assert scores.score_version == SCORE_VERSION


def test_score_bundle_is_deterministic():
    assert score_bundle(full_bundle()) == score_bundle(full_bundle())


def test_linking_a_sparse_judge_never_lowers_score():
    # Adding a freshly created LeetCode account (a couple of easy solves, no
    # contest rating) must not dilute an established BOJ profile: cross-platform
    # aggregation is monotonic — more data only helps.
    base = SnapshotBundle(github=github_fixture(), solvedac=solvedac_fixture())
    sparse_lc = leetcode_fixture().model_copy(
        update={"solved": LeetCodeSolved(easy=2, medium=0, hard=0), "contest_rating": 0}
    )
    with_lc = base.model_copy(update={"leetcode": sparse_lc})

    b, w = score_bundle(base), score_bundle(with_lc)
    assert w.axes.problem_solving >= b.axes.problem_solving
    assert w.axes.depth >= b.axes.depth
    assert w.overall >= b.overall
    assert TIERS.index(w.tier) >= TIERS.index(b.tier)


def test_problem_solving_sums_across_judges():
    # Two judges' solved counts add up (not averaged), so a BOJ+LeetCode profile
    # scores at least as high as BOJ alone with the same BOJ data.
    boj_only = SnapshotBundle(github=github_fixture(), solvedac=solvedac_fixture())
    both = boj_only.model_copy(update={"leetcode": leetcode_fixture()})
    assert score_bundle(both).axes.problem_solving >= score_bundle(boj_only).axes.problem_solving


def test_github_only_has_no_problem_solving():
    scores = score_bundle(_github_only())
    assert scores.axes.problem_solving == 0
    assert scores.axes.open_source > 0


def test_confidence_ordering():
    full = compute_confidence(full_bundle())
    gh_only = compute_confidence(_github_only())
    assert full > gh_only
    assert compute_confidence(SnapshotBundle()) == 0


def test_confidence_partial_github_no_judges_is_low():
    partial = GitHubSnapshot(
        **{
            **github_fixture().model_dump(),
            "status": PlatformStatus.PARTIAL,
            "total_commits": 0,
            "total_pull_requests": 0,
            "total_reviews": 0,
            "active_days": 0,
        }
    )
    assert compute_confidence(SnapshotBundle(github=partial)) < 0.35


def test_leetcode_discounted_vs_solvedac():
    base = SnapshotBundle(github=github_fixture())
    with_sa = compute_confidence(base.model_copy(update={"solvedac": solvedac_fixture()}))
    with_lc = compute_confidence(base.model_copy(update={"leetcode": leetcode_fixture()}))
    assert with_sa > with_lc


def test_tier_boundaries():
    assert compute_tier(0, 1) is Tier.SEED
    assert compute_tier(15, 1) is Tier.BRONZE
    assert compute_tier(14.9, 1) is Tier.SEED
    assert compute_tier(45, 1) is Tier.GOLD
    assert compute_tier(57.9, 1) is Tier.GOLD
    assert compute_tier(58, 1) is Tier.PLATINUM
    assert compute_tier(95, 1) is Tier.MARU


def test_low_confidence_caps_tier():
    assert compute_tier(95, 0.3) is Tier.BRONZE
    assert compute_tier(95, 0.55) is Tier.GOLD
    assert compute_tier(95, 0.15) is Tier.SEED


def test_top_axes_orders_by_score():
    axes = AxisScores(open_source=10, impact=90, consistency=40, problem_solving=70, depth=5)
    assert top_axes(axes, 3) == [Axis.IMPACT, Axis.PROBLEM_SOLVING, Axis.CONSISTENCY]


def test_top_axes_ties_break_by_canonical_order():
    axes = AxisScores(open_source=50, impact=50, consistency=50, problem_solving=50, depth=50)
    assert top_axes(axes, 3) == [Axis.OPEN_SOURCE, Axis.IMPACT, Axis.CONSISTENCY]
