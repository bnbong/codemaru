"""GitHub adapter (GraphQL).

Uses the authenticated GraphQL API for public profile, repository, and
past-year contribution data. A token is required; without one the snapshot is
``unavailable`` (live GitHub data needs ``GITHUB_TOKEN``).

Repositories are paginated so ``total_stars``/``total_forks``/``language_count``
reflect every owned non-fork repo, not just the top page — bounded by
``MAX_REPO_PAGES`` to cap request cost. Parsing lives in pure functions so it can
be tested against saved payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from codemaru.models.snapshot import GitHubSnapshot, PlatformStatus

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# Hard cap on repository pages (100 repos/page). 500 repos is far into the tail
# where additional repos contribute negligible stars/forks.
MAX_REPO_PAGES = 5

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


def _unavailable(login: str, note: str, fetched_at: datetime) -> GitHubSnapshot:
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
) -> GitHubSnapshot:
    """Assemble a GitHubSnapshot from aggregated repo data + contributions."""
    active_days, longest_streak = _active_days_and_streak(contrib.get("contributionCalendar", {}))
    return GitHubSnapshot(
        status=PlatformStatus.OK,
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
    )


def parse_github(user: dict[str, Any], login: str, fetched_at: datetime) -> GitHubSnapshot:
    """Build a GitHubSnapshot from a single ``user`` payload (one repo page)."""
    repos = user.get("repositories", {})
    nodes = repos.get("nodes", []) or []
    stars, forks, languages = parse_repo_nodes(nodes)
    return build_github_snapshot(
        login=user.get("login", login),
        repos_total=int(repos.get("totalCount", 0)),
        stars=stars,
        forks=forks,
        languages=languages,
        followers=int(user.get("followers", {}).get("totalCount", 0)),
        contrib=user.get("contributionsCollection", {}),
        fetched_at=fetched_at,
    )


async def fetch_github(
    login: str,
    *,
    token: str | None,
    fetched_at: datetime,
    client: httpx.AsyncClient,
) -> GitHubSnapshot:
    """Fetch a GitHub snapshot, paginating repos and degrading on failure."""
    if not token:
        return _unavailable(login, "GITHUB_TOKEN not configured", fetched_at)
    headers = {"Authorization": f"bearer {token}"}

    async def _page(cursor: str | None) -> dict[str, Any] | None:
        resp = await client.post(
            GITHUB_GRAPHQL_URL,
            json={"query": _QUERY, "variables": {"login": login, "cursor": cursor}},
            headers=headers,
        )
        if resp.status_code != 200:
            return None
        return (resp.json().get("data") or {}).get("user")

    try:
        first = await _page(None)
        if first is None:
            return _unavailable(login, "user not found", fetched_at)

        repos = first.get("repositories", {})
        stars, forks, languages = parse_repo_nodes(repos.get("nodes", []) or [])
        contrib = first.get("contributionsCollection", {})
        followers = int(first.get("followers", {}).get("totalCount", 0))
        repos_total = int(repos.get("totalCount", 0))
        page_info = repos.get("pageInfo", {})

        pages = 1
        while page_info.get("hasNextPage") and pages < MAX_REPO_PAGES:
            nxt = await _page(page_info.get("endCursor"))
            if nxt is None:  # a later page failed — keep what we have
                break
            nxt_repos = nxt.get("repositories", {})
            s, f, langs = parse_repo_nodes(nxt_repos.get("nodes", []) or [])
            stars += s
            forks += f
            languages |= langs
            page_info = nxt_repos.get("pageInfo", {})
            pages += 1

        return build_github_snapshot(
            login=first.get("login", login),
            repos_total=repos_total,
            stars=stars,
            forks=forks,
            languages=languages,
            followers=followers,
            contrib=contrib,
            fetched_at=fetched_at,
        )
    except Exception:  # noqa: BLE001 - degrade gracefully on any network/schema error
        return _unavailable(login, "request failed", fetched_at)
