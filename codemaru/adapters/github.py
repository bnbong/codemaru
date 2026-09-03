"""GitHub adapter (GraphQL).

Uses the authenticated GraphQL API for public profile, repository, and
past-year contribution data. A token is required; without one the snapshot is
``unavailable`` (live GitHub data needs ``GITHUB_TOKEN``).

Repositories are paginated so ``total_stars``/``total_forks``/``language_count``
reflect every owned non-fork repo, not just the top page — bounded by
``MAX_REPO_PAGES`` to cap request cost, and by an optional ``deadline`` so a
multi-page profile yields the pages it managed rather than blowing the whole
card-build budget. Parsing lives in pure functions so it can be tested against
saved payloads.
"""

from __future__ import annotations

from datetime import datetime
from time import monotonic
from typing import Any

import httpx

from codemaru.models.snapshot import GitHubSnapshot, PlatformStatus
from codemaru.telemetry import log_adapter

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# Hard cap on repository pages (100 repos/page). 500 repos is far into the tail
# where additional repos contribute negligible stars/forks.
MAX_REPO_PAGES = 5

# Note attached when the GraphQL query resolves no such user. A module constant
# because ``codemaru.service`` matches on it to give a missing handle its own,
# longer negative cache TTL — a literal duplicated there would drift.
NOT_FOUND_NOTE = "user not found"

# Upper bound on one follow-up repo page: ``_REPOS_QUERY`` is light, and the
# total card build must stay within the serverless budget. A slow tail page
# degrades to a partial snapshot fast instead of eating the whole request. The
# actual per-page timeout is the smaller of this and what is left of the build
# deadline (see ``_page_timeout``).
MAX_FOLLOWUP_PAGE_TIMEOUT = 3.0

# Headroom subtracted from the remaining budget when sizing a page's timeout, so
# the page gives up fractionally before the outer deadline does — that deadline
# cancels the *whole* fetch, page 1 included.
_PAGE_START_MARGIN = 0.25

# Below this much remaining budget a follow-up page isn't worth starting: the
# timeout it could be given is too short to plausibly complete, and a page that
# is cut off yields nothing while still costing GraphQL quota.
_MIN_PAGE_BUDGET = 1.0

_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    login
    followers { totalCount }
    repositories(
      first: 100
      after: $cursor
      ownerAffiliations: [OWNER]
      isFork: false
      orderBy: { field: STARGAZERS, direction: DESC }
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        forkCount
        primaryLanguage { name }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      totalRepositoriesWithContributedCommits
      contributionCalendar {
        weeks { contributionDays { contributionCount } }
      }
    }
  }
}
"""

# Follow-up repo pages only need repositories — the (expensive) contributions
# aggregation is fetched once on the first page, so re-querying it per page just
# burns latency and GraphQL rate budget on multi-page profiles.
_REPOS_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    login
    repositories(
      first: 100
      after: $cursor
      ownerAffiliations: [OWNER]
      isFork: false
      orderBy: { field: STARGAZERS, direction: DESC }
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        forkCount
        primaryLanguage { name }
      }
    }
  }
}
"""


class _PageStatusError(Exception):
    """A GraphQL response that wasn't 200, carrying the status for classification.

    Raised instead of returning a sentinel so the caller cannot confuse "the API
    refused the request" with "the API answered, and there is no such user" —
    the two get different notes and, downstream, very different cache TTLs.
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code


def unavailable_snapshot(login: str, note: str, fetched_at: datetime) -> GitHubSnapshot:
    """An all-zero snapshot standing in for data this platform could not supply.

    Public so the service layer can substitute one when the card-build budget
    cuts a fetch short, without duplicating the field list."""
    return GitHubSnapshot(
        status=PlatformStatus.UNAVAILABLE,
        fetched_at=fetched_at,
        note=note,
        login=login,
        public_repos=0,
        total_stars=0,
        total_forks=0,
        followers=0,
        total_commits=0,
        total_pull_requests=0,
        total_issues=0,
        total_reviews=0,
        contributed_repos=0,
        active_days=0,
        longest_streak=0,
        language_count=0,
    )


def parse_repo_nodes(nodes: list[dict[str, Any]]) -> tuple[int, int, set[str]]:
    """Return (stars, forks, language-names) aggregated over repo nodes."""
    stars = sum(int(n.get("stargazerCount", 0)) for n in nodes)
    forks = sum(int(n.get("forkCount", 0)) for n in nodes)
    languages = {
        n["primaryLanguage"]["name"]
        for n in nodes
        if n.get("primaryLanguage") and n["primaryLanguage"].get("name")
    }
    return stars, forks, languages


def top_owned_repo(nodes: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (stars, forks) of the most-starred repo.

    The live query already orders repos by stargazers desc, but we pick the max
    defensively so the helper is correct regardless of input order (test
    fixtures, future parser reuse).
    """
    if not nodes:
        return 0, 0
    top = max(nodes, key=lambda n: int(n.get("stargazerCount", 0)))
    return int(top.get("stargazerCount", 0)), int(top.get("forkCount", 0))


def _active_days_and_streak(calendar: dict[str, Any]) -> tuple[int, int]:
    """Count active days and the longest consecutive active-day streak."""
    counts: list[int] = []
    for week in calendar.get("weeks", []):
        for day in week.get("contributionDays", []):
            counts.append(int(day.get("contributionCount", 0)))
    active = sum(1 for c in counts if c > 0)
    longest = 0
    current = 0
    for c in counts:
        if c > 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return active, longest


def build_github_snapshot(
    *,
    login: str,
    repos_total: int,
    stars: int,
    forks: int,
    languages: set[str],
    followers: int,
    contrib: dict[str, Any],
    fetched_at: datetime,
    top_repo_stars: int = 0,
    top_repo_forks: int = 0,
    partial: bool = False,
    note: str | None = None,
) -> GitHubSnapshot:
    """Assemble a GitHubSnapshot from aggregated repo data + contributions.

    ``partial=True`` (with ``note``) means a repository page actually failed to
    load, so the aggregates are incomplete. A successful fetch that merely hits
    the intentional page cap stays ``ok`` (with an informational ``note``) — it
    is current data, not a degradation, so it must not trigger stale fallback.
    """
    active_days, longest_streak = _active_days_and_streak(contrib.get("contributionCalendar", {}))
    return GitHubSnapshot(
        status=PlatformStatus.PARTIAL if partial else PlatformStatus.OK,
        note=note,
        fetched_at=fetched_at,
        login=login,
        public_repos=repos_total,
        total_stars=stars,
        total_forks=forks,
        followers=followers,
        total_commits=int(contrib.get("totalCommitContributions", 0)),
        total_pull_requests=int(contrib.get("totalPullRequestContributions", 0)),
        total_issues=int(contrib.get("totalIssueContributions", 0)),
        total_reviews=int(contrib.get("totalPullRequestReviewContributions", 0)),
        contributed_repos=int(contrib.get("totalRepositoriesWithContributedCommits", 0)),
        active_days=active_days,
        longest_streak=longest_streak,
        language_count=len(languages),
        top_owned_repo_stars=top_repo_stars,
        top_owned_repo_forks=top_repo_forks,
    )


def parse_github(user: dict[str, Any], login: str, fetched_at: datetime) -> GitHubSnapshot:
    """Build a GitHubSnapshot from a single ``user`` payload (one repo page)."""
    repos = user.get("repositories", {})
    nodes = repos.get("nodes", []) or []
    stars, forks, languages = parse_repo_nodes(nodes)
    top_stars, top_forks = top_owned_repo(nodes)
    return build_github_snapshot(
        login=user.get("login", login),
        repos_total=int(repos.get("totalCount", 0)),
        stars=stars,
        forks=forks,
        languages=languages,
        followers=int(user.get("followers", {}).get("totalCount", 0)),
        contrib=user.get("contributionsCollection", {}),
        fetched_at=fetched_at,
        top_repo_stars=top_stars,
        top_repo_forks=top_forks,
    )


def _page_timeout(deadline: float | None) -> httpx.Timeout | None:
    """Timeout for the next follow-up page, or ``None`` to stop paginating.

    Sized from what is actually left of the shared build budget rather than from
    a fixed constant: a request can spend its wall clock in any phase (connect,
    write, read, pool), so bounding one phase leaves the others free to outrun
    the deadline — and that deadline cancels the entire GitHub fetch, discarding
    page 1 too. The single number therefore applies to every phase.
    """
    if deadline is None:
        return httpx.Timeout(MAX_FOLLOWUP_PAGE_TIMEOUT)
    remaining = deadline - monotonic()
    if remaining < _MIN_PAGE_BUDGET:
        return None
    return httpx.Timeout(min(MAX_FOLLOWUP_PAGE_TIMEOUT, remaining - _PAGE_START_MARGIN))


async def fetch_github(
    login: str,
    *,
    token: str | None,
    fetched_at: datetime,
    client: httpx.AsyncClient,
    deadline: float | None = None,
) -> GitHubSnapshot:
    """Fetch a GitHub snapshot, paginating repos and degrading on failure.

    ``deadline`` is a ``time.monotonic()`` instant shared with the rest of the
    card build. Pagination is sequential, so it is checked cooperatively before
    each follow-up page: running out of time stops the loop with the pages
    already aggregated rather than losing the fetch to a cancellation. Page 1 is
    never skipped — without it there is no snapshot at all.
    """
    # A thin wrapper around the real fetch so every exit path — ok, partial,
    # unavailable — is logged from one place.
    started = monotonic()
    snapshot = await _fetch_github(
        login, token=token, fetched_at=fetched_at, client=client, deadline=deadline
    )
    log_adapter("github", login, status=snapshot.status, note=snapshot.note, started=started)
    return snapshot


async def _fetch_github(
    login: str,
    *,
    token: str | None,
    fetched_at: datetime,
    client: httpx.AsyncClient,
    deadline: float | None,
) -> GitHubSnapshot:
    if not token:
        return unavailable_snapshot(login, "GITHUB_TOKEN not configured", fetched_at)
    headers = {"Authorization": f"bearer {token}"}

    async def _page(
        cursor: str | None,
        *,
        query: str = _QUERY,
        timeout: httpx.Timeout | None = None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Fetch one page; ``timeout=None`` uses the client's own budget.

        Returns ``(user, errors)`` — ``errors`` is GraphQL's top-level
        ``errors`` array, which can be non-empty even on an HTTP 200 (rate
        limiting, resolver/authorization failures, a malformed query). The
        caller needs both to tell a real missing user apart from a request that
        merely came back with no ``data.user``.
        """
        timeout_arg = timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT
        resp = await client.post(
            GITHUB_GRAPHQL_URL,
            json={"query": query, "variables": {"login": login, "cursor": cursor}},
            headers=headers,
            timeout=timeout_arg,
        )
        if resp.status_code != 200:
            raise _PageStatusError(resp.status_code)
        body = resp.json()
        user = (body.get("data") or {}).get("user")
        errors = body.get("errors")
        return user, (errors if isinstance(errors, list) else [])

    try:
        try:
            first, first_errors = await _page(None)
        except _PageStatusError as exc:
            # An HTTP failure is about the *request*, not the handle: an expired
            # token (401), a rate limit (403) or a GitHub outage (5xx) says
            # nothing about whether this user exists. Reporting it as
            # NOT_FOUND_NOTE would earn it the long not-found cache TTL and pin
            # the outage on every handle that asked during it.
            return unavailable_snapshot(login, f"http {exc.status_code}", fetched_at)
        if first is None:
            # HTTP 200 with ``data.user: null`` alone is ambiguous: GitHub uses
            # the exact same shape for "Could not resolve to a User" (a stable
            # answer about the handle) and for a request that failed for some
            # other reason (rate limiting, an authorization failure, a malformed
            # query) and simply has no data to return. The ``errors`` array is
            # what tells them apart, so only a GraphQL ``NOT_FOUND`` error — or
            # no error at all — earns the long not-found cache TTL; any other
            # error type gets the short negative TTL instead, keyed off its type.
            not_found = any(
                isinstance(err, dict) and err.get("type") == "NOT_FOUND" for err in first_errors
            )
            if not first_errors or not_found:
                return unavailable_snapshot(login, NOT_FOUND_NOTE, fetched_at)
            error_type = next(
                (
                    err.get("type")
                    for err in first_errors
                    if isinstance(err, dict) and err.get("type")
                ),
                None,
            )
            return unavailable_snapshot(
                login, f"graphql error: {error_type or 'unknown'}", fetched_at
            )

        repos = first.get("repositories", {})
        first_nodes = repos.get("nodes", []) or []
        stars, forks, languages = parse_repo_nodes(first_nodes)
        # First page is ordered by stars desc, so its first node is the global top.
        top_stars, top_forks = top_owned_repo(first_nodes)
        contrib = first.get("contributionsCollection", {})
        followers = int(first.get("followers", {}).get("totalCount", 0))
        repos_total = int(repos.get("totalCount", 0))
        page_info = repos.get("pageInfo", {})

        pages = 1
        page_failed = False
        budget_stopped = False
        while page_info.get("hasNextPage") and pages < MAX_REPO_PAGES:
            page_timeout = _page_timeout(deadline)
            if page_timeout is None:
                budget_stopped = True
                break
            try:
                nxt, _nxt_errors = await _page(
                    page_info.get("endCursor"),
                    query=_REPOS_QUERY,
                    timeout=page_timeout,
                )
            except Exception:  # noqa: BLE001 - a timeout/network error/non-200 on
                # a later page is just a failed page: keep the first page
                # (followers, contributions, top repos) instead of discarding the
                # whole fetch.
                nxt = None
            # Follow-up pages keep today's behaviour: any problem — HTTP failure,
            # no data.user, or a GraphQL error alongside a populated user (rare,
            # but the aggregates from this page would be incomplete either way)
            # — is treated as a failed page rather than being classified further.
            if nxt is None:  # a later page failed — keep what we have
                page_failed = True
                break
            nxt_repos = nxt.get("repositories", {})
            s, f, langs = parse_repo_nodes(nxt_repos.get("nodes", []) or [])
            stars += s
            forks += f
            languages |= langs
            page_info = nxt_repos.get("pageInfo", {})
            pages += 1

        if page_failed:
            # Genuine incompleteness from an error → partial (may stale-fall-back).
            partial, note = True, "repository data incomplete (a page failed to load)"
        elif budget_stopped:
            # Out of time, not broken: everything fetched so far is current data,
            # and repos are stars-desc so the unread tail contributes ~nothing.
            # Stays ok, exactly like hitting the page cap.
            partial, note = (
                False,
                f"aggregated top {pages * 100} repositories by stars "
                "(pagination stopped for the time budget)",
            )
        elif page_info.get("hasNextPage"):
            # Hit the intentional cap on a successful fetch → still ok, just noted.
            # Repos are ordered by stars desc, so the tail contributes ~nothing.
            partial, note = False, f"aggregated top {MAX_REPO_PAGES * 100} repositories by stars"
        else:
            partial, note = False, None

        return build_github_snapshot(
            login=first.get("login", login),
            repos_total=repos_total,
            stars=stars,
            forks=forks,
            languages=languages,
            followers=followers,
            contrib=contrib,
            fetched_at=fetched_at,
            top_repo_stars=top_stars,
            top_repo_forks=top_forks,
            partial=partial,
            note=note,
        )
    except Exception:  # noqa: BLE001 - degrade gracefully on any network/schema error
        return unavailable_snapshot(login, "request failed", fetched_at)
