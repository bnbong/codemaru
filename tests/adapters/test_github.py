from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest

from codemaru.adapters import github
from codemaru.adapters.github import (
    _QUERY,
    _REPOS_QUERY,
    GITHUB_GRAPHQL_URL,
    fetch_github,
    parse_github,
    top_owned_repo,
)
from codemaru.models.snapshot import PlatformStatus
from tests.adapters.fakes import FakeClient, FakeResponse

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def test_top_owned_repo_picks_max_and_handles_empty():
    assert top_owned_repo([]) == (0, 0)  # no repos
    nodes = [
        {"stargazerCount": 10, "forkCount": 2},
        {"stargazerCount": 99, "forkCount": 40},  # the max, even if not first
        {"stargazerCount": 50, "forkCount": 7},
    ]
    assert top_owned_repo(nodes) == (99, 40)


def _user_payload() -> dict[str, Any]:
    # Two active days then a gap then three active days → streak of 3, 5 active.
    days = [1, 2, 0, 1, 4, 2]
    return {
        "login": "octocat",
        "followers": {"totalCount": 340},
        "repositories": {
            "totalCount": 42,
            "nodes": [
                {"stargazerCount": 1000, "forkCount": 150, "primaryLanguage": {"name": "Python"}},
                {"stargazerCount": 280, "forkCount": 60, "primaryLanguage": {"name": "Go"}},
                {"stargazerCount": 0, "forkCount": 0, "primaryLanguage": None},
            ],
        },
        "contributionsCollection": {
            "totalCommitContributions": 1850,
            "totalPullRequestContributions": 164,
            "totalIssueContributions": 98,
            "totalPullRequestReviewContributions": 120,
            "totalRepositoriesWithContributedCommits": 37,
            "contributionCalendar": {
                "weeks": [{"contributionDays": [{"contributionCount": c} for c in days]}]
            },
        },
    }


def test_parse_github_aggregates_fields():
    snap = parse_github(_user_payload(), "octocat", _TS)
    assert snap.status is PlatformStatus.OK
    assert snap.total_stars == 1280
    assert snap.total_forks == 210
    assert snap.public_repos == 42
    assert snap.followers == 340
    assert snap.total_commits == 1850
    assert snap.language_count == 2  # Python, Go (None ignored)
    assert snap.active_days == 5
    assert snap.longest_streak == 3
    # Repos are stars-desc, so the first node is the representative project.
    assert snap.top_owned_repo_stars == 1000
    assert snap.top_owned_repo_forks == 150


async def test_fetch_github_ok_sends_auth_and_login_variable():
    client = FakeClient(
        {GITHUB_GRAPHQL_URL: FakeResponse(200, {"data": {"user": _user_payload()}})}
    )
    snap = await fetch_github(
        "octocat", token="tok123", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    assert snap.status is PlatformStatus.OK
    assert snap.login == "octocat"
    call = client.calls[0]
    assert call.headers is not None and call.headers["Authorization"] == "bearer tok123"
    assert call.json["variables"]["login"] == "octocat"


def _page(
    nodes: list[dict[str, Any]], *, has_next: bool, cursor: str | None = None
) -> dict[str, Any]:
    return {
        "data": {
            "user": {
                "login": "octocat",
                "followers": {"totalCount": 10},
                "repositories": {
                    "totalCount": 150,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "nodes": nodes,
                },
                "contributionsCollection": {"contributionCalendar": {"weeks": []}},
            }
        }
    }


async def test_fetch_github_paginates_and_sums_all_pages():
    page1 = _page(
        [{"stargazerCount": 500, "forkCount": 50, "primaryLanguage": {"name": "Python"}}],
        has_next=True,
        cursor="CUR",
    )
    page2 = _page(
        [{"stargazerCount": 120, "forkCount": 20, "primaryLanguage": {"name": "Rust"}}],
        has_next=False,
    )
    client = FakeClient({GITHUB_GRAPHQL_URL: [FakeResponse(200, page1), FakeResponse(200, page2)]})
    snap = await fetch_github(
        "octocat", token="t", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    assert snap.total_stars == 620  # summed across both pages
    assert snap.total_forks == 70
    assert snap.language_count == 2  # Python + Rust union
    assert snap.public_repos == 150
    # second request used the first page's endCursor
    assert client.calls[1].json["variables"]["cursor"] == "CUR"
    # Page 1 uses the full query (incl. the expensive contributionsCollection);
    # follow-up pages use the lighter repos-only query so contributions aren't
    # re-fetched per page. Guards against a refactor silently reverting to _QUERY.
    assert client.calls[0].json["query"] == _QUERY
    assert client.calls[1].json["query"] == _REPOS_QUERY
    assert "contributionsCollection" in client.calls[0].json["query"]
    assert "contributionsCollection" not in client.calls[1].json["query"]
    assert snap.status is PlatformStatus.OK  # all pages fetched


async def test_fetch_github_later_page_failure_is_partial():
    page1 = _page(
        [{"stargazerCount": 500, "forkCount": 50, "primaryLanguage": {"name": "Python"}}],
        has_next=True,
        cursor="CUR",
    )
    client = FakeClient({GITHUB_GRAPHQL_URL: [FakeResponse(200, page1), FakeResponse(500, {})]})
    snap = await fetch_github(
        "octocat", token="t", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    # First page's data is kept, but the snapshot is flagged partial.
    assert snap.status is PlatformStatus.PARTIAL
    assert snap.total_stars == 500
    assert snap.public_repos == 150
    assert "incomplete" in (snap.note or "")


async def test_fetch_github_page_cap_reached_stays_ok(monkeypatch: pytest.MonkeyPatch):
    # Hitting the cap on a *successful* fetch is not a degradation — it stays ok
    # (so it never triggers stale fallback), with an informational note.
    monkeypatch.setattr(github, "MAX_REPO_PAGES", 1)
    page1 = _page(
        [{"stargazerCount": 500, "forkCount": 50, "primaryLanguage": {"name": "Python"}}],
        has_next=True,  # more pages exist, but the cap stops us
        cursor="CUR",
    )
    client = FakeClient({GITHUB_GRAPHQL_URL: FakeResponse(200, page1)})
    snap = await fetch_github(
        "octocat", token="t", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    assert snap.status is PlatformStatus.OK
    assert "top 100" in (snap.note or "")


async def test_fetch_github_without_token_is_unavailable():
    client = FakeClient({})
    snap = await fetch_github(
        "octocat", token=None, fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    assert snap.status is PlatformStatus.UNAVAILABLE
    assert "TOKEN" in (snap.note or "")


async def test_fetch_github_user_not_found_is_unavailable():
    client = FakeClient({GITHUB_GRAPHQL_URL: FakeResponse(200, {"data": {"user": None}})})
    snap = await fetch_github(
        "ghost", token="t", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    assert snap.status is PlatformStatus.UNAVAILABLE


async def test_fetch_github_network_error_is_unavailable():
    client = FakeClient({GITHUB_GRAPHQL_URL: httpx.ConnectError("boom")})
    snap = await fetch_github(
        "octocat", token="t", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    assert snap.status is PlatformStatus.UNAVAILABLE
