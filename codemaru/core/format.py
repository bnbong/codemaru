"""Display formatting helpers shared by the summary builder and renderer."""

from __future__ import annotations

_SOLVEDAC_GROUPS = ["Unrated", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Ruby"]
_ROMAN = ["V", "IV", "III", "II", "I"]


def compact_number(value: int | float) -> str:
    """Compact a count, e.g. 1234 -> '1.2k', 2_500_000 -> '2.5M'."""
    abs_value = abs(value)
    if abs_value < 1000:
        return str(round(value))
    if abs_value < 1_000_000:
        return f"{_trim(value / 1000)}k"
    return f"{_trim(value / 1_000_000)}M"


def _trim(n: float) -> str:
    rounded = round(n * 10) / 10
    return f"{rounded:g}"


def solvedac_tier_name(tier: int) -> str:
    """Map a solved.ac numeric tier (0..30) to a readable label.

    1..5 = Bronze V..I, 6..10 = Silver V..I, ..., 26..30 = Ruby V..I.
    """
    if tier <= 0:
        return "Unrated"
    group_index = (tier - 1) // 5 + 1  # 1..6
    group = _SOLVEDAC_GROUPS[group_index] if group_index < len(_SOLVEDAC_GROUPS) else "Ruby"
    roman = _ROMAN[(tier - 1) % 5]
    return f"{group} {roman}"
