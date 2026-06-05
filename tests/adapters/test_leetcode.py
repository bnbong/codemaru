from datetime import UTC, datetime
from typing import Any, cast

import httpx

from codemaru.adapters.leetcode import GRAPHQL_URL, fetch_leetcode, parse_leetcode
from codemaru.models.snapshot import PlatformStatus
from tests.adapters.fakes import FakeClient, FakeResponse

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def _data(rating: float | None = 1872.4) -> dict[str, Any]:
    return {
        "matchedUser": {
            "username": "demo",
            "profile": {"ranking": 84210},
            "submitStatsGlobal": {
                "acSubmissionNum": [
                    {"difficulty": "All", "count": 686},
                    {"difficulty": "Easy", "count": 210},
                    {"difficulty": "Medium", "count": 380},
                    {"difficulty": "Hard", "count": 96},
                ]
            },
        },
        "userContestRanking": {"rating": rating} if rating is not None else None,
    }


def test_parse_leetcode_solved_ranking_and_rating():
    snap = parse_leetcode(_data(), "demo", _TS)
    assert snap.status is PlatformStatus.OK
    assert (snap.solved.easy, snap.solved.medium, snap.solved.hard) == (210, 380, 96)
    assert snap.ranking == 84210
    assert snap.contest_rating == 1872  # rounded


def test_parse_leetcode_without_contest_rating():
    snap = parse_leetcode(_data(rating=None), "demo", _TS)
    assert snap.contest_rating is None


async def test_fetch_leetcode_ok_sends_username_and_headers():
    client = FakeClient({GRAPHQL_URL: FakeResponse(200, {"data": _data()})})
    snap = await fetch_leetcode("demo", fetched_at=_TS, client=cast(httpx.AsyncClient, client))
    assert snap.status is PlatformStatus.OK
    assert snap.solved.hard == 96
    call = client.calls[0]
    assert call.json["variables"]["username"] == "demo"
    assert call.headers is not None
    assert call.headers["Referer"] == "https://leetcode.com"
    assert call.headers["Content-Type"] == "application/json"


async def test_fetch_leetcode_user_not_found_is_unavailable():
    client = FakeClient({GRAPHQL_URL: FakeResponse(200, {"data": {"matchedUser": None}})})
    snap = await fetch_leetcode("ghost", fetched_at=_TS, client=cast(httpx.AsyncClient, client))
    assert snap.status is PlatformStatus.UNAVAILABLE


async def test_fetch_leetcode_network_error_is_unavailable():
    client = FakeClient({GRAPHQL_URL: httpx.ConnectError("boom")})
    snap = await fetch_leetcode("demo", fetched_at=_TS, client=cast(httpx.AsyncClient, client))
    assert snap.status is PlatformStatus.UNAVAILABLE
