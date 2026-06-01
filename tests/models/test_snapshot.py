from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from codemaru.models.snapshot import PlatformStatus, SolvedAcSnapshot

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def _snapshot(tier: int) -> SolvedAcSnapshot:
    return SolvedAcSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        handle="demo",
        tier=tier,
        rating=1500,
        solved_count=100,
        class_level=3,
    )


@pytest.mark.parametrize("tier", [0, 1, 30])
def test_valid_solvedac_tiers(tier: int):
    assert _snapshot(tier).tier == tier


@pytest.mark.parametrize("tier", [31, -1, 99])
def test_invalid_solvedac_tiers_rejected(tier: int):
    # solved.ac only defines 0 (Unrated) .. 30 (Ruby I).
    with pytest.raises(ValidationError):
        _snapshot(tier)
