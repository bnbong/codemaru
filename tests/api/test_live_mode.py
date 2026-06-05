"""Live-mode orchestration: adapters are monkeypatched so no network is used."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from codemaru import service
from codemaru.models.snapshot import (
    GitHubSnapshot,
    LeetCodeSnapshot,
    LeetCodeSolved,
    PlatformStatus,
    SolvedAcSnapshot,
)

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def _github(login: str, *, status: PlatformStatus = PlatformStatus.OK) -> GitHubSnapshot:
    return GitHubSnapshot(
        status=status,
        fetched_at=_TS,
        login=login,
        public_repos=10,
        total_stars=500,
        total_forks=40,
        followers=80,
        total_commits=900,
        total_pull_requests=70,
        total_issues=30,
        total_reviews=40,
        contributed_repos=12,
        active_days=150,
        longest_streak=20,
        language_count=5,
    )


@pytest.fixture
def fake_adapters(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    called = {"github": False, "solvedac": False, "leetcode": False}

    async def fake_github(login: str, **_: Any) -> GitHubSnapshot:
        called["github"] = True
        return _github(login)

    async def fake_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        called["solvedac"] = True
        return SolvedAcSnapshot(
            status=PlatformStatus.OK,
            fetched_at=_TS,
            handle=handle,
            tier=12,
            rating=1200,
            solved_count=600,
            class_level=4,
        )

    async def fake_leetcode(username: str, **_: Any) -> LeetCodeSnapshot:
        called["leetcode"] = True
        return LeetCodeSnapshot(
            status=PlatformStatus.OK,
            fetched_at=_TS,
            username=username,
            solved=LeetCodeSolved(easy=100, medium=150, hard=30),
            ranking=50000,
            contest_rating=1700,
        )

    monkeypatch.setattr(service, "fetch_github", fake_github)
    monkeypatch.setattr(service, "fetch_solvedac", fake_solvedac)
    monkeypatch.setattr(service, "fetch_leetcode", fake_leetcode)
    return called


def test_live_summary_uses_adapters(
    client: TestClient, live_mode: None, fake_adapters: dict[str, bool]
):
    res = client.get(
        "/api/summary.json", params={"github": "octocat", "boj": "baek", "leetcode": "lc"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["snapshots"]["github"]["login"] == "octocat"
    assert data["snapshots"]["solvedac"]["handle"] == "baek"
    assert data["snapshots"]["leetcode"]["username"] == "lc"
    assert data["overallStatus"] == "ok"
    assert fake_adapters == {"github": True, "solvedac": True, "leetcode": True}


def test_live_only_requested_platforms_are_fetched(
    client: TestClient, live_mode: None, fake_adapters: dict[str, bool]
):
    res = client.get("/api/summary.json", params={"github": "octocat"})
    assert res.status_code == 200
    data = res.json()
    assert data["snapshots"]["solvedac"] is None
    assert data["snapshots"]["leetcode"] is None
    assert fake_adapters == {"github": True, "solvedac": False, "leetcode": False}


def test_live_one_adapter_failure_degrades_to_partial(
    client: TestClient, live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    async def ok_github(login: str, **_: Any) -> GitHubSnapshot:
        return _github(login)

    async def dead_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        # Adapters never raise; a failure surfaces as an unavailable snapshot.
        return SolvedAcSnapshot(
            status=PlatformStatus.UNAVAILABLE,
            fetched_at=_TS,
            handle=handle,
            tier=0,
            rating=0,
            solved_count=0,
            class_level=0,
        )

    monkeypatch.setattr(service, "fetch_github", ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", dead_solvedac)

    res = client.get("/api/summary.json", params={"github": "octocat", "boj": "baek"})
    assert res.status_code == 200
    data = res.json()
    # The card still renders; the failed platform just marks the card partial.
    assert data["overallStatus"] == "partial"


def test_live_card_svg_renders(client: TestClient, live_mode: None, fake_adapters: dict[str, bool]):
    res = client.get("/api/card.svg", params={"github": "octocat", "boj": "baek"})
    assert res.status_code == 200
    assert "x-codemaru-error" not in res.headers
    assert res.text.startswith("<svg")
