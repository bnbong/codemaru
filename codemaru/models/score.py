"""Scoring types: the five radar axes, the tier ladder, and normalized scores."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Axis(StrEnum):
    """The five radar axes used on the card."""

    OPEN_SOURCE = "openSource"
    IMPACT = "impact"
    CONSISTENCY = "consistency"
    PROBLEM_SOLVING = "problemSolving"
    DEPTH = "depth"


# Canonical axis order — used for radar layout and as the stable tie-break order.
AXES: tuple[Axis, ...] = (
    Axis.OPEN_SOURCE,
    Axis.IMPACT,
    Axis.CONSISTENCY,
    Axis.PROBLEM_SOLVING,
    Axis.DEPTH,
)

AXIS_LABELS: dict[Axis, str] = {
    Axis.OPEN_SOURCE: "Open Source",
    Axis.IMPACT: "Impact",
    Axis.CONSISTENCY: "Consistency",
    Axis.PROBLEM_SOLVING: "Problem Solving",
    Axis.DEPTH: "Depth",
}

# Labels under the strength badges. Most use the full axis name; the two longest
# are shortened so they fit beneath a 30px tile.
AXIS_SHORT_LABELS: dict[Axis, str] = {
    Axis.OPEN_SOURCE: "Open Source",
    Axis.IMPACT: "Impact",
    Axis.CONSISTENCY: "Consistency",
    Axis.PROBLEM_SOLVING: "Solving",
    Axis.DEPTH: "Depth",
}


class Tier(StrEnum):
    """codemaru tiers, ordered lowest to highest. Seed = low-data / new users."""

    SEED = "Seed"
    BRONZE = "Bronze"
    SILVER = "Silver"
    GOLD = "Gold"
    PLATINUM = "Platinum"
    DIAMOND = "Diamond"
    MASTER = "Master"
    MARU = "Maru"


# Ordered lowest → highest; index is used for min() comparisons in tier capping.
TIERS: tuple[Tier, ...] = (
    Tier.SEED,
    Tier.BRONZE,
    Tier.SILVER,
    Tier.GOLD,
    Tier.PLATINUM,
    Tier.DIAMOND,
    Tier.MASTER,
    Tier.MARU,
)


class AxisScores(BaseModel):
    """Per-axis scores, each in the 0-100 range."""

    open_source: float = Field(ge=0, le=100, serialization_alias="openSource")
    impact: float = Field(ge=0, le=100)
    consistency: float = Field(ge=0, le=100)
    problem_solving: float = Field(ge=0, le=100, serialization_alias="problemSolving")
    depth: float = Field(ge=0, le=100)

    model_config = {"populate_by_name": True}

    def get(self, axis: Axis) -> float:
        """Return the score for the given axis."""
        value: float = getattr(self, _AXIS_ATTR[axis])
        return value


# Map each Axis enum to its AxisScores attribute name.
_AXIS_ATTR: dict[Axis, str] = {
    Axis.OPEN_SOURCE: "open_source",
    Axis.IMPACT: "impact",
    Axis.CONSISTENCY: "consistency",
    Axis.PROBLEM_SOLVING: "problem_solving",
    Axis.DEPTH: "depth",
}


class NormalizedScores(BaseModel):
    """Presentation-ready scores produced by the scoring engine."""

    axes: AxisScores
    overall: float = Field(ge=0, le=100)
    # Confidence (0-1) caps the maximum tier; it is NOT shown on the card but is
    # kept here so /api/summary.json stays transparent.
    confidence: float = Field(ge=0, le=1)
    tier: Tier
    score_version: str = Field(serialization_alias="scoreVersion")

    model_config = {"populate_by_name": True}
