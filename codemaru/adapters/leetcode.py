"""LeetCode adapter (unofficial GraphQL).

LeetCode has no official public API; this uses the same GraphQL endpoint the
website calls. It is experimental and may change or be blocked, so any failure
maps cleanly to ``unavailable`` and never breaks the card.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from codemaru.models.snapshot import LeetCodeSnapshot, LeetCodeSolved, PlatformStatus

GRAPHQL_URL = "https://leetcode.com/graphql"

_QUERY = """
query($username: String!) {
  matchedUser(username: $username) {
    username
    profile { ranking }
    submitStatsGlobal { acSubmissionNum { difficulty count } }
  }
  userContestRanking(username: $username) { rating }
}
"""


def _unavailable(username: str, note: str, fetched_at: datetime) -> LeetCodeSnapshot:
    return LeetCodeSnapshot(
        status=PlatformStatus.UNAVAILABLE,
        fetched_at=fetched_at,
        note=note,
        username=username,
        solved=LeetCodeSolved(),
        ranking=0,
        contest_rating=None,
    )


def parse_leetcode(data: dict[str, Any], username: str, fetched_at: datetime) -> LeetCodeSnapshot:
    """Build a LeetCodeSnapshot from the GraphQL ``data`` object."""
    user = data.get("matchedUser") or {}
    by_difficulty = {
        entry.get("difficulty"): int(entry.get("count", 0))
        for entry in user.get("submitStatsGlobal", {}).get("acSubmissionNum", [])
    }
    ranking = int((user.get("profile") or {}).get("ranking", 0) or 0)

    contest = data.get("userContestRanking") or {}
    rating_raw = contest.get("rating")
    contest_rating = round(rating_raw) if rating_raw else None

    return LeetCodeSnapshot(
        status=PlatformStatus.OK,
        fetched_at=fetched_at,
        username=user.get("username", username),
        solved=LeetCodeSolved(
            easy=by_difficulty.get("Easy", 0),
            medium=by_difficulty.get("Medium", 0),
            hard=by_difficulty.get("Hard", 0),
        ),
        ranking=max(0, ranking),
        contest_rating=contest_rating,
    )


async def fetch_leetcode(
    username: str,
    *,
    fetched_at: datetime,
    client: httpx.AsyncClient,
) -> LeetCodeSnapshot:
    """Fetch a LeetCode snapshot, mapping any failure to ``unavailable``."""
    try:
        resp = await client.post(
            GRAPHQL_URL,
            json={"query": _QUERY, "variables": {"username": username}},
            headers={"Referer": "https://leetcode.com", "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            return _unavailable(username, f"http {resp.status_code}", fetched_at)
        data = (resp.json() or {}).get("data") or {}
        if data.get("matchedUser") is None:
            return _unavailable(username, "user not found", fetched_at)
        return parse_leetcode(data, username, fetched_at)
    except Exception:  # noqa: BLE001 - degrade gracefully on any network/schema error
        return _unavailable(username, "request failed", fetched_at)
