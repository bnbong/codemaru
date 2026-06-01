import math

from codemaru.core.normalization import clamp, linear_score, log_score, weighted_average


def test_clamp_bounds_and_nan():
    assert clamp(5, 0, 10) == 5
    assert clamp(-3, 0, 10) == 0
    assert clamp(99, 0, 10) == 10
    assert clamp(math.nan, 2, 10) == 2


def test_log_score_endpoints_and_monotonic():
    assert log_score(0, 1000) == 0
    assert round(log_score(1000, 1000)) == 100
    assert log_score(2000, 1000) <= 100
    assert log_score(50, 1000) < log_score(500, 1000)
    assert log_score(100, 0) == 0


def test_log_score_is_concave():
    early = log_score(100, 1000) - log_score(50, 1000)
    late = log_score(550, 1000) - log_score(500, 1000)
    assert early > late


def test_linear_score():
    assert round(linear_score(182.5, 365)) == 50
    assert linear_score(400, 365) == 100


def test_weighted_average():
    assert weighted_average([(100, 1), (0, 1)]) == 50
    assert weighted_average([]) == 0
    assert weighted_average([(80, 0)]) == 0
