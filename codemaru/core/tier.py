"""Tier derivation. The overall score picks a base tier; confidence then caps how
high that tier may go. The final tier is the lower of the two."""

from __future__ import annotations

from codemaru.models.score import TIERS, Tier

# Lower bound (inclusive) of the overall score for each tier, highest first.
_SCORE_THRESHOLDS: list[tuple[Tier, float]] = [
    (Tier.MARU, 90),
    (Tier.MASTER, 80),
    (Tier.DIAMOND, 70),
    (Tier.PLATINUM, 58),
    (Tier.GOLD, 45),
    (Tier.SILVER, 30),
    (Tier.BRONZE, 15),
    (Tier.SEED, 0),
]

# Maximum tier permitted at a given confidence level, highest first. Calibrated
# against the volume-weighted confidence in confidence.py:
#   - A strong single-source profile (e.g. GitHub-only, confidence ~0.6) can now
#     reach **Master** — deep activity in one domain is no longer capped at Gold.
#   - **Maru** is reserved for an all-round, multi-platform "pentagon": its cap
#     needs confidence only reachable with both substantial OSS *and* algorithm
#     evidence (a single source can't get there).
_CONFIDENCE_CAPS: list[tuple[Tier, float]] = [
    (Tier.MARU, 0.85),
    (Tier.MASTER, 0.55),
    (Tier.DIAMOND, 0.45),
    (Tier.PLATINUM, 0.35),
    (Tier.GOLD, 0.25),
    (Tier.SILVER, 0.15),
    (Tier.BRONZE, 0.07),
    (Tier.SEED, 0.0),
]


def _tier_from_score(overall: float) -> Tier:
    for tier, minimum in _SCORE_THRESHOLDS:
        if overall >= minimum:
            return tier
    return Tier.SEED


def _tier_cap_from_confidence(confidence: float) -> Tier:
    for tier, minimum in _CONFIDENCE_CAPS:
        if confidence >= minimum:
            return tier
    return Tier.SEED


def compute_tier(overall: float, confidence: float) -> Tier:
    """Return the tier for an overall score, capped by confidence."""
    base = _tier_from_score(overall)
    cap = _tier_cap_from_confidence(confidence)
    final_index = min(TIERS.index(base), TIERS.index(cap))
    return TIERS[final_index]
