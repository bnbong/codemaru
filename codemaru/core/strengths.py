"""Derives a user's strongest axes for the trophy display. Pure + deterministic."""

from __future__ import annotations

from codemaru.models.score import AXES, Axis, AxisScores


def top_axes(axes: AxisScores, count: int = 3) -> list[Axis]:
    """Return the ``count`` highest-scoring axes, descending.

    Ties are broken by the canonical AXES order so the result is stable.
    """
    order = {axis: i for i, axis in enumerate(AXES)}
    ranked = sorted(AXES, key=lambda axis: (-axes.get(axis), order[axis]))
    return ranked[:count]
