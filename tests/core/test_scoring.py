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
    # A fresh account: a couple of easy solves, and no contest rating (None, as
    # the real adapter reports it — not 0).
    sparse_lc = leetcode_fixture().model_copy(
        update={"solved": LeetCodeSolved(easy=2, medium=0, hard=0), "contest_rating": None}
    )
    with_lc = base.model_copy(update={"leetcode": sparse_lc})

    b, w = score_bundle(base), score_bundle(with_lc)
    assert w.axes.problem_solving >= b.axes.problem_solving
    assert w.axes.depth >= b.axes.depth
    assert w.overall >= b.overall
    assert TIERS.index(w.tier) >= TIERS.index(b.tier)


def test_empty_judge_does_not_dilute_github_only_depth():
    # A GitHub-only profile's depth comes from its representative project and
    # language breadth (no judge pillar). Linking a usable but empty judge (no
    # hard solves, no contest rating) must not pull that depth down.
    gh_only = SnapshotBundle(github=github_fixture())
    empty_lc = leetcode_fixture().model_copy(
        update={"solved": LeetCodeSolved(easy=0, medium=0, hard=0), "contest_rating": None}
    )
    with_lc = gh_only.model_copy(update={"leetcode": empty_lc})
    assert score_bundle(with_lc).axes.depth >= score_bundle(gh_only).axes.depth


def test_sparse_leetcode_adds_no_confidence_and_no_tier_jump():
    # The core fix: a freshly-made LeetCode account (a single solve) must add
    # ~no confidence, so it can never bump the tier a step. (Old bug: presence
    # alone added a flat 0.105 confidence, crossing a cap threshold.)
    base = SnapshotBundle(github=github_fixture(), solvedac=solvedac_fixture())
    sparse_lc = leetcode_fixture().model_copy(
        update={"solved": LeetCodeSolved(easy=1, medium=0, hard=0), "contest_rating": None}
    )
    with_lc = base.model_copy(update={"leetcode": sparse_lc})

    b, w = score_bundle(base), score_bundle(with_lc)
    assert abs(w.confidence - b.confidence) < 0.005  # negligible
    assert w.tier == b.tier  # no tier jump


def test_substantial_leetcode_raises_confidence_and_score():
    # A real solve history (the demo LeetCode fixture) should count.
    base = SnapshotBundle(github=github_fixture(), solvedac=solvedac_fixture())
    with_lc = base.model_copy(update={"leetcode": leetcode_fixture()})
    b, w = score_bundle(base), score_bundle(with_lc)
    assert w.confidence > b.confidence
    assert w.axes.problem_solving >= b.axes.problem_solving


def test_single_source_can_reach_master_but_not_maru():
    # A strong single-source profile (GitHub-only confidence ~0.6) now caps at
    # Master, not Gold; Maru is reserved for the multi-platform pentagon, whose
    # confidence a single source cannot reach.
    assert compute_tier(95, 0.50) is Tier.DIAMOND  # below the Master cap
    assert compute_tier(95, 0.60) is Tier.MASTER  # single-source range -> Master
    assert compute_tier(95, 0.84) is Tier.MASTER  # just below the Maru cap
    assert compute_tier(95, 0.86) is Tier.MARU


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


def _gh_repo(stars: int, forks: int, langs: int):
    return github_fixture().model_copy(
        update={
            "top_owned_repo_stars": stars,
            "top_owned_repo_forks": forks,
            "language_count": langs,
        }
    )


def test_depth_rewards_a_flagship_project_without_judges():
    # A hugely-starred owned project gives high Depth even with no judge data and
    # few languages — depth via "built something significant" (the torvalds case).
    flagship = _gh_repo(stars=180_000, forks=54_000, langs=2)
    assert score_bundle(SnapshotBundle(github=flagship)).axes.depth >= 90


def test_depth_not_inflated_by_language_breadth_alone():
    # No flagship and no judges, just many languages => breadth only fills <=15%
    # headroom, so a polyglot dabbler stays modest and never outranks a flagship.
    dabbler = _gh_repo(stars=0, forks=0, langs=12)
    flagship = _gh_repo(stars=180_000, forks=54_000, langs=2)
    dabbler_depth = score_bundle(SnapshotBundle(github=dabbler)).axes.depth
    assert dabbler_depth <= 16  # ~15 (breadth-only)
    assert score_bundle(SnapshotBundle(github=flagship)).axes.depth > dabbler_depth


def test_depth_high_from_strong_judges_without_a_project():
    # Algorithm depth alone (no notable repo, one language) still yields high Depth.
    gh = _gh_repo(stars=0, forks=0, langs=1)
    bundle = SnapshotBundle(github=gh, solvedac=solvedac_fixture(), leetcode=leetcode_fixture())
    assert score_bundle(bundle).axes.depth >= 90


def test_confidence_credits_a_flagship_not_just_recent_activity():
    # Low recent activity, but a hugely-starred owned project => confidence stays
    # high (a significant flagship is verifiable evidence), so the tier cap isn't
    # pinned low just because the profile is currently quiet.
    quiet = github_fixture().model_copy(
        update={
            "total_commits": 5,
            "total_pull_requests": 0,
            "total_reviews": 0,
            "active_days": 12,
            "top_owned_repo_stars": 0,
            "top_owned_repo_forks": 0,
        }
    )
    flagship = quiet.model_copy(
        update={"top_owned_repo_stars": 180_000, "top_owned_repo_forks": 54_000}
    )
    assert compute_confidence(SnapshotBundle(github=flagship)) > compute_confidence(
        SnapshotBundle(github=quiet)
    )


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
    assert compute_tier(95, 0.20) is Tier.SILVER
    assert compute_tier(95, 0.30) is Tier.GOLD
    assert compute_tier(95, 0.05) is Tier.SEED


def test_top_axes_orders_by_score():
    axes = AxisScores(open_source=10, impact=90, consistency=40, problem_solving=70, depth=5)
    assert top_axes(axes, 3) == [Axis.IMPACT, Axis.PROBLEM_SOLVING, Axis.CONSISTENCY]


def test_top_axes_ties_break_by_canonical_order():
    axes = AxisScores(open_source=50, impact=50, consistency=50, problem_solving=50, depth=50)
    assert top_axes(axes, 3) == [Axis.OPEN_SOURCE, Axis.IMPACT, Axis.CONSISTENCY]
