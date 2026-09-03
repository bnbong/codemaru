"""Difficulty-band mapping shared by judges that use the solved.ac tier scale.

solved.ac numbers problems 0..30 (0 = Unrated, 1..30 = Bronze V .. Ruby I) and
groups them into six five-wide bands. Other judges reuse the same axis, so the
band table lives here rather than inside one adapter.

``codemaru.adapters.solvedac`` re-exports these names, so existing imports from
that module keep working.
"""

from __future__ import annotations

from typing import Any

from codemaru.models.snapshot import DifficultyDistribution

# solved.ac level → coarse difficulty band (level 0 is Unrated and ignored).
_BANDS = [
    (1, 5, "bronze"),
    (6, 10, "silver"),
    (11, 15, "gold"),
    (16, 20, "platinum"),
    (21, 25, "diamond"),
    (26, 30, "ruby"),
]


def _band_for(level: int) -> str | None:
    for low, high, name in _BANDS:
        if low <= level <= high:
            return name
    return None


def parse_difficulty(stats: list[dict[str, Any]]) -> DifficultyDistribution:
    """Sum solved counts per difficulty band from the problem_stats payload."""
    totals = {name: 0 for _, _, name in _BANDS}
    for entry in stats:
        band = _band_for(int(entry.get("level", 0)))
        if band is not None:
            totals[band] += int(entry.get("solved", 0))
    return DifficultyDistribution(**totals)
