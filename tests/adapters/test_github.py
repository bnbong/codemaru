from datetime import UTC, datetime
from time import monotonic
from typing import Any, cast

import httpx
import pytest

from codemaru.adapters import github
from codemaru.adapters.github import (
    _QUERY,
    _REPOS_QUERY,
    GITHUB_GRAPHQL_URL,
    NOT_FOUND_NOTE,
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
    nodes: list[dict[str, Any]],
    *,
    has_next: bool,
    cursor: str | None = None,
    commits: int = 0,
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
                "contributionsCollection": {
                    "totalCommitContributions": commits,
                    "contributionCalendar": {"weeks": []},
                },
            }
        }
    }


# Budget of the client the service hands to the adapter, mirrored here so the
# per-request timeout assertions have something to compare against.
_CLIENT_TIMEOUT = 10.0


def _mock_client(
    steps: list[httpx.Response | Exception], seen: list[httpx.Request]
) -> httpx.AsyncClient:
    """A real AsyncClient over MockTransport, one ``step`` consumed per request.

    Unlike FakeClient this drives httpx itself, so a transport error raised
    mid-pagination and the per-request ``timeout=`` behave as they do against the
    live API (httpx records the latter in ``request.extensions["timeout"]``).
    """
    remaining = list(steps)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        step = remaining.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(_CLIENT_TIMEOUT, connect=5.0),
    )


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
        commits=1850,
    )
    client = FakeClient({GITHUB_GRAPHQL_URL: [FakeResponse(200, page1), FakeResponse(500, {})]})
    snap = await fetch_github(
        "octocat", token="t", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    # First page's data is kept, but the snapshot is flagged partial.
    assert snap.status is PlatformStatus.PARTIAL
    assert snap.total_stars == 500
    assert snap.public_repos == 150
    assert snap.followers == 10
    assert snap.total_commits == 1850
    assert snap.top_owned_repo_stars == 500
    assert "incomplete" in (snap.note or "")


async def test_fetch_github_later_page_timeout_is_partial():
    # Regression: a timeout on page 2+ used to escape the pagination loop and hit
    # the outer handler, throwing away the first page (followers, contributions,
    # top repos) and rendering a Seed card. It must degrade like any failed page.
    page1 = _page(
        [{"stargazerCount": 500, "forkCount": 50, "primaryLanguage": {"name": "Python"}}],
        has_next=True,
        cursor="CUR",
        commits=1850,
    )
    seen: list[httpx.Request] = []
    client = _mock_client([httpx.Response(200, json=page1), httpx.ReadTimeout("timed out")], seen)
    async with client:
        snap = await fetch_github("octocat", token="t", fetched_at=_TS, client=client)
    assert snap.status is PlatformStatus.PARTIAL
    assert "incomplete" in (snap.note or "")
    # Everything page 1 already paid for survives.
    assert snap.total_stars == 500
    assert snap.total_forks == 50
    assert snap.language_count == 1
    assert snap.public_repos == 150
    assert snap.followers == 10
    assert snap.total_commits == 1850
    assert snap.top_owned_repo_stars == 500
    assert snap.top_owned_repo_forks == 50
    assert len(seen) == 2  # stopped at the failed page


async def test_fetch_github_first_page_timeout_is_unavailable():
    # Nothing was fetched, so there is no partial data to keep — still unavailable.
    seen: list[httpx.Request] = []
    client = _mock_client([httpx.ReadTimeout("timed out")], seen)
    async with client:
        snap = await fetch_github("octocat", token="t", fetched_at=_TS, client=client)
    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == "request failed"
    assert snap.total_stars == 0


async def test_fetch_github_followup_pages_use_shorter_timeout():
    # Page 1 carries the expensive contributions query and keeps the client's
    # budget; the repos-only follow-up pages get a tighter one so a slow tail
    # can't eat the whole card build.
    page1 = _page(
        [{"stargazerCount": 500, "forkCount": 50, "primaryLanguage": {"name": "Python"}}],
        has_next=True,
        cursor="CUR",
    )
    page2 = _page(
        [{"stargazerCount": 120, "forkCount": 20, "primaryLanguage": {"name": "Rust"}}],
        has_next=False,
    )
    seen: list[httpx.Request] = []
    client = _mock_client([httpx.Response(200, json=page1), httpx.Response(200, json=page2)], seen)
    async with client:
        snap = await fetch_github("octocat", token="t", fetched_at=_TS, client=client)
    assert snap.status is PlatformStatus.OK
    assert snap.total_stars == 620
    assert seen[0].extensions["timeout"]["read"] == _CLIENT_TIMEOUT
    # Every phase is bounded, not just `read`: a request can spend its wall clock
    # connecting, writing or waiting on the pool just as easily.
    assert set(seen[1].extensions["timeout"].values()) == {github.MAX_FOLLOWUP_PAGE_TIMEOUT}
    assert github.MAX_FOLLOWUP_PAGE_TIMEOUT < _CLIENT_TIMEOUT


async def test_fetch_github_shortens_the_followup_page_to_fit_the_deadline():
    # Regression: the per-page timeout used to be a fixed 3s regardless of how
    # much budget was left, so a page could still be in flight when the outer
    # asyncio.timeout fired — and that cancels the WHOLE fetch, discarding page 1
    # (followers, contributions, top repos), the exact loss the deadline exists to
    # prevent. The page must give up before the deadline does.
    page1 = _page(
        [{"stargazerCount": 500, "forkCount": 50, "primaryLanguage": {"name": "Python"}}],
        has_next=True,
        cursor="CUR",
    )
    page2 = _page(
        [{"stargazerCount": 120, "forkCount": 20, "primaryLanguage": {"name": "Rust"}}],
        has_next=False,
    )
    seen: list[httpx.Request] = []
    client = _mock_client([httpx.Response(200, json=page1), httpx.Response(200, json=page2)], seen)
    async with client:
        snap = await fetch_github(
            "octocat", token="t", fetched_at=_TS, client=client, deadline=monotonic() + 2.0
        )
    assert snap.status is PlatformStatus.OK
    assert snap.total_stars == 620  # the page still ran, just on a tighter clock
    timeout = seen[1].extensions["timeout"]
    assert set(timeout.values()) == {timeout["read"]}  # one number, every phase
    assert timeout["read"] <= 1.75  # 2.0 remaining minus the start margin
    assert timeout["read"] < github.MAX_FOLLOWUP_PAGE_TIMEOUT


async def test_fetch_github_stops_paginating_when_the_build_budget_is_spent():
    # The card build shares one budget; GitHub is the only adapter that paginates,
    # so it checks the deadline cooperatively rather than being cancelled and
    # losing page 1 entirely.
    page1 = _page(
        [{"stargazerCount": 500, "forkCount": 50, "primaryLanguage": {"name": "Python"}}],
        has_next=True,
        cursor="CUR",
        commits=1850,
    )
    seen: list[httpx.Request] = []
    client = _mock_client([httpx.Response(200, json=page1)], seen)
    async with client:
        snap = await fetch_github(
            "octocat",
            token="t",
            fetched_at=_TS,
            client=client,
            deadline=monotonic() - 1,  # already spent
        )
    assert len(seen) == 1  # page 1 is never skipped; no follow-up was attempted
    # Out of time is not a failure: the data is current, so it stays ok and never
    # triggers stale fallback.
    assert snap.status is PlatformStatus.OK
    assert "budget" in (snap.note or "")
    assert snap.total_stars == 500
    assert snap.total_commits == 1850
    assert snap.followers == 10


async def test_fetch_github_paginates_normally_with_a_distant_deadline():
    page1 = _page(
        [{"stargazerCount": 500, "forkCount": 50, "primaryLanguage": {"name": "Python"}}],
        has_next=True,
        cursor="CUR",
    )
    page2 = _page(
        [{"stargazerCount": 120, "forkCount": 20, "primaryLanguage": {"name": "Rust"}}],
        has_next=False,
    )
    seen: list[httpx.Request] = []
    client = _mock_client([httpx.Response(200, json=page1), httpx.Response(200, json=page2)], seen)
    async with client:
        snap = await fetch_github(
            "octocat", token="t", fetched_at=_TS, client=client, deadline=monotonic() + 3600
        )
    assert len(seen) == 2
    assert snap.total_stars == 620
    assert snap.note is None


def test_page_timeout_is_sized_from_the_remaining_budget():
    from codemaru.adapters.github import _MIN_PAGE_BUDGET, _PAGE_START_MARGIN, _page_timeout

    # No deadline -> the plain cap, on every phase.
    no_deadline = _page_timeout(None)
    assert no_deadline is not None
    assert set(no_deadline.as_dict().values()) == {github.MAX_FOLLOWUP_PAGE_TIMEOUT}

    # Plenty of budget -> still capped, never longer than the cap.
    plenty = _page_timeout(monotonic() + 3600)
    assert plenty is not None
    assert plenty.read == github.MAX_FOLLOWUP_PAGE_TIMEOUT

    # A near deadline shortens the page instead of letting it outrun the budget.
    near = _page_timeout(monotonic() + 2.0)
    assert near is not None
    assert near.read is not None
    assert near.read <= 2.0 - _PAGE_START_MARGIN
    assert set(near.as_dict().values()) == {near.read}  # one number, all phases

    # Too little left to be worth starting -> stop paginating.
    assert _page_timeout(monotonic() + _MIN_PAGE_BUDGET / 2) is None
    assert _page_timeout(monotonic() - 1) is None  # already spent


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
    # HTTP 200 with `data.user: null` is GraphQL's "Could not resolve to a User":
    # a stable answer about this handle, and the only thing that earns the long
    # not-found cache TTL.
    client = FakeClient({GITHUB_GRAPHQL_URL: FakeResponse(200, {"data": {"user": None}})})
    snap = await fetch_github(
        "ghost", token="t", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == NOT_FOUND_NOTE


@pytest.mark.parametrize("status", [401, 403, 500, 502])
async def test_fetch_github_first_page_http_error_is_not_user_not_found(status: int):
    # Regression: every non-200 used to be reported as "user not found", which
    # earns the 10-minute not-found TTL — so one expired token, rate limit or
    # GitHub outage poisoned the cache of every handle that asked during it.
    client = FakeClient({GITHUB_GRAPHQL_URL: FakeResponse(status, {})})
    snap = await fetch_github(
        "octocat", token="expired", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    assert snap.status is PlatformStatus.UNAVAILABLE
    assert snap.note == f"http {status}"
    assert snap.note != NOT_FOUND_NOTE


async def test_fetch_github_network_error_is_unavailable():
    client = FakeClient({GITHUB_GRAPHQL_URL: httpx.ConnectError("boom")})
    snap = await fetch_github(
        "octocat", token="t", fetched_at=_TS, client=cast(httpx.AsyncClient, client)
    )
    assert snap.status is PlatformStatus.UNAVAILABLE
