from datetime import UTC, datetime
from typing import cast

import httpx

from codemaru.adapters.solvedac import (
    SHOW_URL,
    STATS_URL,
    fetch_solvedac,
    parse_difficulty,
    parse_solvedac,
)
from codemaru.models.snapshot import PlatformStatus
from tests.adapters.fakes import FakeClient, FakeResponse

_TS = datetime(2026, 5, 31, tzinfo=UTC)

_SHOW = {"handle": "demo", "tier": 18, "rating": 1640, "solvedCount": 1420, "class": 6}
_STATS = [
    {"level": 3, "solved": 100},  # bronze
    {"level": 8, "solved": 200},  # silver
    {"level": 18, "solved": 50},  # platinum
    {"level": 0, "solved": 999},  # unrated, ignored
]


def test_parse_difficulty_buckets_by_band():
    dist = parse_difficulty(_STATS)
    assert dist.bronze == 100
    assert dist.silver == 200
    assert dist.platinum == 50
    assert dist.gold == 0


def test_parse_solvedac_clamps_out_of_range_tier():
    snap = parse_solvedac({**_SHOW, "tier": 99}, None, "demo", _TS)
    assert snap.tier == 30


async def test_fetch_solvedac_ok_with_distribution():
    client = FakeClient({SHOW_URL: FakeResponse(200, _SHOW), STATS_URL: FakeResponse(200, _STATS)})
    snap = await fetch_solvedac("demo", fetched_at=_TS, client=cast(httpx.AsyncClient, client))
    assert snap.status is PlatformStatus.OK
    assert snap.tier == 18
    assert snap.solved_count == 1420
    assert snap.difficulty.silver == 200
    # handle is passed as a query param.
    show_call = next(c for c in client.calls if c.url == SHOW_URL)
    assert show_call.params == {"handle": "demo"}


async def test_fetch_solvedac_stats_failure_is_partial():
    client = FakeClient({SHOW_URL: FakeResponse(200, _SHOW), STATS_URL: httpx.ConnectError("boom")})
    snap = await fetch_solvedac("demo", fetched_at=_TS, client=cast(httpx.AsyncClient, client))
    # Profile metrics survive, but the missing distribution marks it partial.
    assert snap.status is PlatformStatus.PARTIAL
    assert snap.solved_count == 1420
    assert snap.difficulty.silver == 0
    assert "distribution" in (snap.note or "")


async def test_fetch_solvedac_user_not_found_is_unavailable():
    client = FakeClient({SHOW_URL: FakeResponse(404, {"error": "not found"})})
    snap = await fetch_solvedac("ghost", fetched_at=_TS, client=cast(httpx.AsyncClient, client))
    assert snap.status is PlatformStatus.UNAVAILABLE
