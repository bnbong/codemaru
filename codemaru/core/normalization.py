"""Normalization primitives shared by the scoring engine.

Raw counts (stars, solved problems, commits) are unbounded and skewed, so they
are never summed directly. These helpers compress them onto a stable 0-100 scale
using logarithmic saturation: diminishing returns at the top, while still
rewarding early growth.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a value to an inclusive [low, high] range (NaN maps to low)."""
    if math.isnan(value):
        return low
    return min(high, max(low, value))


def round_to(value: float, decimals: int = 0) -> float:
    """Round to a fixed number of decimal places (default: integer)."""
    factor = 10**decimals
    return float(round(value * factor) / factor)


def log_score(value: float, saturation: float) -> float:
    """Map an unbounded non-negative count onto 0-100 via a logarithmic curve.

    ``saturation`` is the count at which the score reaches ~100.
    """
    if saturation <= 0:
        return 0.0
    v = max(0.0, value)
    score = (math.log1p(v) / math.log1p(saturation)) * 100
    return clamp(round_to(score, 1), 0, 100)


def linear_score(value: float, maximum: float) -> float:
    """Linear 0-100 mapping with clamping; for already-bounded inputs."""
    if maximum <= 0:
        return 0.0
    return clamp(round_to((value / maximum) * 100, 1), 0, 100)


def weighted_average(components: Iterable[tuple[float, float]]) -> float:
    """Weighted average of (score, weight) pairs.

    Weights need not sum to 1; they are normalized internally. Zero total weight
    yields 0.
    """
    items = list(components)
    total_weight = sum(weight for _, weight in items)
    if total_weight <= 0:
        return 0.0
    weighted = sum(score * weight for score, weight in items)
    return clamp(round_to(weighted / total_weight, 1), 0, 100)
