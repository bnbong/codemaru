"""Radar chart geometry. All polygon math lives here so layout code stays
declarative. No external charting library."""

from __future__ import annotations

import math

from codemaru.render.xml import fmt_num


def _axis_angle(i: int, count: int) -> float:
    """Angle (radians) of axis ``i`` of ``count``, starting at the top, clockwise."""
    return -math.pi / 2 + (i / count) * math.pi * 2


def vertex(
    cx: float, cy: float, radius: float, i: int, count: int, fraction: float
) -> tuple[float, float]:
    """Coordinates of axis ``i`` at a given radius fraction (0..1)."""
    angle = _axis_angle(i, count)
    return (cx + math.cos(angle) * radius * fraction, cy + math.sin(angle) * radius * fraction)


def polygon_points(cx: float, cy: float, radius: float, fractions: list[float]) -> str:
    """Build a ``points`` attribute string for the polygon at the given fractions."""
    parts: list[str] = []
    count = len(fractions)
    for i, fraction in enumerate(fractions):
        x, y = vertex(cx, cy, radius, i, count, max(0.0, min(1.0, fraction)))
        parts.append(f"{fmt_num(x)},{fmt_num(y)}")
    return " ".join(parts)


def ring_fractions(rings: int) -> list[float]:
    """Evenly spaced concentric ring fractions, e.g. [0.25, 0.5, 0.75, 1]."""
    return [(i + 1) / rings for i in range(rings)]
