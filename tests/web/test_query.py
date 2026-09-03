import pytest

from codemaru.web.query import QueryError, parse_request


def _parse(**kw):
    base = {"github": "octocat", "boj": None, "leetcode": None, "theme": None, "compact": None}
    base.update(kw)
    return parse_request(**base)


def test_animate_defaults_on_when_absent():
    _profile, options = _parse(animate=None)
    assert options.animate is True


def test_animate_can_be_disabled():
    _profile, options = _parse(animate="false")
    assert options.animate is False


def test_animate_accepts_truthy_values():
    for value in ("true", "1", "yes", "on"):
        _profile, options = _parse(animate=value)
        assert options.animate is True


def test_animate_rejects_garbage():
    with pytest.raises(QueryError):
        _parse(animate="maybe")


def test_compact_still_defaults_false():
    _profile, options = _parse(compact=None)
    assert options.compact is False


def test_jungol_is_parsed_onto_the_profile():
    profile, _options = _parse(jungol="demo_handle")
    assert profile.jungol == "demo_handle"


def test_jungol_absent_stays_none():
    profile, _options = _parse()
    assert profile.jungol is None


def test_blank_jungol_becomes_none():
    profile, _options = _parse(jungol="   ")
    assert profile.jungol is None


def test_invalid_jungol_raises_a_named_query_error():
    with pytest.raises(QueryError, match="jungol"):
        _parse(jungol="bad handle")
