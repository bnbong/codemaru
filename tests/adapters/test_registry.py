"""The judge-platform registry: lookups, and the invariants callers rely on."""

from __future__ import annotations

from codemaru.adapters import solvedac, tiers
from codemaru.adapters.registry import JUDGES, judge_by_key, judge_by_param
from codemaru.models.snapshot import SnapshotBundle


def test_registry_order_is_solvedac_leetcode_then_jungol():
    # Registry order is the canonical order for judges(), the cache key's handle
    # segment, and generated query strings — reordering is a breaking change.
    # A new judge is APPENDED, which is why jungol sits last.
    assert [p.key for p in JUDGES] == ["solvedac", "leetcode", "jungol"]
    assert [p.param for p in JUDGES] == ["boj", "leetcode", "jungol"]


def test_registry_keys_and_params_are_unique():
    assert len({p.key for p in JUDGES}) == len(JUDGES)
    assert len({p.param for p in JUDGES}) == len(JUDGES)


def test_registry_keys_are_snapshot_bundle_fields():
    # judges()/judge_snapshot() resolve a key straight to a bundle attribute, so
    # a key with no matching field would silently drop that judge.
    fields = set(SnapshotBundle.model_fields)
    assert {p.key for p in JUDGES} <= fields


def test_judge_by_key():
    solved = judge_by_key("solvedac")
    assert solved is not None
    assert solved.param == "boj"
    assert solved.trust == 1.00
    assert solved.saturation == 2200
    assert solved.weight == 0.25
    assert solved.shared_client is False
    assert judge_by_key("nope") is None


def test_judge_by_param():
    leetcode = judge_by_param("leetcode")
    assert leetcode is not None
    assert leetcode.key == "leetcode"
    assert leetcode.label == "LeetCode"
    assert leetcode.trust == 0.75
    assert leetcode.saturation == 1400
    assert leetcode.weight == 0.15
    assert leetcode.shared_client is True
    # solved.ac is requested as `boj`, so its key is not a valid param.
    assert judge_by_param("solvedac") is None


def test_judge_by_param_jungol():
    jungol = judge_by_param("jungol")
    assert jungol is not None
    assert jungol.key == "jungol"
    assert jungol.label == "JungOl / 정올"
    # Lower trust than solved.ac (an undocumented internal payload), and a
    # saturation scaled to JungOl's much smaller problem pool.
    assert jungol.trust == 0.60
    assert jungol.saturation == 900
    assert jungol.weight == 0.10
    assert jungol.shared_client is True


def test_every_judge_has_a_fetcher_and_an_unavailable_constructor():
    # A key missing from the fetch map is silently never fetched; one missing
    # from _JUDGE_UNAVAILABLE raises KeyError the moment the card-build budget
    # cuts that judge's task short.
    from codemaru.service import _JUDGE_UNAVAILABLE, _judge_fetchers

    keys = {p.key for p in JUDGES}
    assert keys <= set(_judge_fetchers())
    assert keys <= set(_JUDGE_UNAVAILABLE)


def test_every_judge_is_a_parse_request_parameter():
    # web/query.parse_request keeps the judge params explicit in its signature
    # (they mirror the public query contract) but assembles the profile by walking
    # the registry. A row whose param never reaches the signature is therefore
    # accepted nowhere and silently always None.
    import inspect

    from codemaru.web.query import parse_request

    names = set(inspect.signature(parse_request).parameters)
    assert {p.param for p in JUDGES} <= names


def test_every_judge_is_a_query_parameter_on_every_public_route():
    # The three surfaces that take handles from a URL: the card, the JSON summary,
    # and the generator page. Read off the OpenAPI schema rather than the function
    # signatures, so this asserts the contract FastAPI actually publishes.
    from codemaru.app import create_app

    schema = create_app().openapi()
    params = {p.param for p in JUDGES}
    for path in ("/api/card.svg", "/api/summary.json", "/"):
        declared = {p["name"] for p in schema["paths"][path]["get"].get("parameters", [])}
        missing = params - declared
        assert not missing, f"{path} does not accept {sorted(missing)}"


def test_judge_platforms_are_frozen():
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        JUDGES[0].trust = 0.1  # type: ignore[misc]


def test_solvedac_still_re_exports_the_shared_tier_helpers():
    # The band table moved to adapters/tiers.py; existing imports must keep working.
    assert solvedac.parse_difficulty is tiers.parse_difficulty
    assert solvedac._band_for is tiers._band_for
    assert solvedac._BANDS is tiers._BANDS
