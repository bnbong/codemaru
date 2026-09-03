"""Live-mode orchestration: adapters are monkeypatched so no network is used."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from codemaru import service
from codemaru.models.snapshot import (
    DifficultyDistribution,
    GitHubSnapshot,
    JungOlSnapshot,
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
    called = {"github": False, "solvedac": False, "leetcode": False, "jungol": False}

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

    async def fake_jungol(handle: str, **_: Any) -> JungOlSnapshot:
        called["jungol"] = True
        return JungOlSnapshot(
            status=PlatformStatus.OK,
            fetched_at=_TS,
            handle=handle,
            account_id=42058,
            tier=7,
            rating=340,
            rank=4791,
            solved_count=70,
            difficulty=DifficultyDistribution(bronze=15, silver=14, gold=11, platinum=1),
        )

    monkeypatch.setattr(service, "fetch_github", fake_github)
    monkeypatch.setattr(service, "fetch_solvedac", fake_solvedac)
    monkeypatch.setattr(service, "fetch_leetcode", fake_leetcode)
    monkeypatch.setattr(service, "fetch_jungol", fake_jungol)
    return called


def test_live_summary_uses_adapters(
    client: TestClient, live_mode: None, fake_adapters: dict[str, bool]
):
    res = client.get(
        "/api/summary.json",
        params={"github": "octocat", "boj": "baek", "leetcode": "lc", "jungol": "jo"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["snapshots"]["github"]["login"] == "octocat"
    assert data["snapshots"]["solvedac"]["handle"] == "baek"
    assert data["snapshots"]["leetcode"]["username"] == "lc"
    assert data["snapshots"]["jungol"]["handle"] == "jo"
    assert data["overallStatus"] == "ok"
    assert fake_adapters == {
        "github": True,
        "solvedac": True,
        "leetcode": True,
        "jungol": True,
    }


def test_live_only_requested_platforms_are_fetched(
    client: TestClient, live_mode: None, fake_adapters: dict[str, bool]
):
    res = client.get("/api/summary.json", params={"github": "octocat"})
    assert res.status_code == 200
    data = res.json()
    assert data["snapshots"]["solvedac"] is None
    assert data["snapshots"]["leetcode"] is None
    assert data["snapshots"]["jungol"] is None
    assert fake_adapters == {
        "github": True,
        "solvedac": False,
        "leetcode": False,
        "jungol": False,
    }


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


def test_live_camo_does_not_record_unknown_handle(
    client: TestClient, live_mode: None, monkeypatch: pytest.MonkeyPatch
):
    # A spoofed `User-Agent: camo` for a non-existent handle (GitHub snapshot
    # `unavailable`) must NOT be recorded — otherwise anyone could inflate the
    # badge and grow the KV set without bound.
    async def missing_github(login: str, **_: Any) -> GitHubSnapshot:
        return _github(login, status=PlatformStatus.UNAVAILABLE)

    recorded: list[str] = []

    async def _spy(handle: str) -> None:
        recorded.append(handle)

    monkeypatch.setattr(service, "fetch_github", missing_github)
    monkeypatch.setattr("codemaru.web.routes.record_embed", _spy)
    res = client.get(
        "/api/card.svg",
        params={"github": "ghost-user-404"},
        headers={"User-Agent": "github-camo/abc"},
    )
    assert res.status_code == 200  # still renders a (degraded) card
    assert recorded == []  # but nothing counted


def _dead_solvedac_snapshot(handle: str) -> SolvedAcSnapshot:
    return SolvedAcSnapshot(
        status=PlatformStatus.UNAVAILABLE,
        fetched_at=_TS,
        handle=handle,
        tier=0,
        rating=0,
        solved_count=0,
        class_level=0,
    )


@pytest.fixture
def degraded_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """GitHub is fine, solved.ac is down -> a `partial` summary."""

    async def ok_github(login: str, **_: Any) -> GitHubSnapshot:
        return _github(login)

    async def dead_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        return _dead_solvedac_snapshot(handle)

    monkeypatch.setattr(service, "fetch_github", ok_github)
    monkeypatch.setattr(service, "fetch_solvedac", dead_solvedac)


def test_degraded_card_is_cached_briefly_at_the_cdn(
    client: TestClient, live_mode: None, degraded_adapters: None, monkeypatch: pytest.MonkeyPatch
):
    # An hour of CDN caching would keep serving the degraded card long after the
    # platform recovered — nothing purges the edge entry.
    async def _noop(handle: str) -> None:
        return None

    monkeypatch.setattr("codemaru.web.routes.record_embed", _noop)
    res = client.get(
        "/api/card.svg",
        params={"github": "octocat", "boj": "baek"},
        headers={"User-Agent": "github-camo/x"},
    )
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=60"
    assert res.headers["cdn-cache-control"] == "public, s-maxage=60, stale-while-revalidate=300"
    assert (
        res.headers["vercel-cdn-cache-control"] == "public, s-maxage=60, stale-while-revalidate=300"
    )


def test_healthy_card_keeps_the_long_cdn_ttl(
    client: TestClient,
    live_mode: None,
    fake_adapters: dict[str, bool],
    monkeypatch: pytest.MonkeyPatch,
):
    async def _noop(handle: str) -> None:
        return None

    monkeypatch.setattr("codemaru.web.routes.record_embed", _noop)
    res = client.get(
        "/api/card.svg",
        params={"github": "octocat", "boj": "baek"},
        headers={"User-Agent": "github-camo/x"},
    )
    assert res.headers["cache-control"] == "public, max-age=300"
    assert "s-maxage=3600" in res.headers["cdn-cache-control"]


def test_degraded_summary_json_is_cached_briefly(
    client: TestClient, live_mode: None, degraded_adapters: None
):
    res = client.get("/api/summary.json", params={"github": "octocat", "boj": "baek"})
    assert res.status_code == 200
    assert res.json()["overallStatus"] == "partial"
    assert res.headers["cache-control"] == "public, max-age=60"
    assert "s-maxage=60" in res.headers["cdn-cache-control"]


def test_stale_summary_json_is_cached_briefly(
    client: TestClient,
    live_mode: None,
    fake_adapters: dict[str, bool],
    monkeypatch: pytest.MonkeyPatch,
):
    # A stale-fallback copy carries the restored `ok` status, so only the `stale`
    # flag can keep it off the long CDN TTL.
    params = {"github": "octocat", "boj": "baek"}
    assert client.get("/api/summary.json", params=params).json()["overallStatus"] == "ok"
    service._cache.clear()

    async def dead_solvedac(handle: str, **_: Any) -> SolvedAcSnapshot:
        return _dead_solvedac_snapshot(handle)

    monkeypatch.setattr(service, "fetch_solvedac", dead_solvedac)

    res = client.get("/api/summary.json", params=params)
    data = res.json()
    assert data["stale"] is True
    assert data["overallStatus"] == "ok"  # restored from the last good read
    assert res.headers["cache-control"] == "public, max-age=60"
    assert "s-maxage=60" in res.headers["cdn-cache-control"]


def test_live_jungol_is_exposed_on_the_wire_with_its_own_fields(
    client: TestClient, live_mode: None, fake_adapters: dict[str, bool]
):
    # `snapshots.jungol` and `input.jungol` are additive: nothing about the
    # existing solvedac / leetcode keys changes.
    res = client.get("/api/summary.json", params={"github": "octocat", "jungol": "jo"})
    data = res.json()

    assert data["input"]["jungol"] == "jo"
    jungol = data["snapshots"]["jungol"]
    assert jungol["source"] == "jungol"
    assert jungol["accountId"] == 42058
    assert jungol["tier"] == 7
    assert jungol["rating"] == 340
    assert jungol["rank"] == 4791
    assert jungol["solvedCount"] == 70
    assert jungol["difficulty"]["gold"] == 11
    # Only jungol was requested, so the other judges stay absent.
    assert data["snapshots"]["solvedac"] is None
    assert fake_adapters["jungol"] is True
    assert fake_adapters["solvedac"] is False


def test_live_jungol_only_profile_gets_the_jungol_tier_metric(
    client: TestClient, live_mode: None, fake_adapters: dict[str, bool]
):
    data = client.get("/api/summary.json", params={"github": "octocat", "jungol": "jo"}).json()
    labels = {m["key"]: m["label"] for m in data["metrics"]}
    assert labels["jungol"] == "JungOl Tier"
    assert "boj" not in labels


def test_live_a_dead_jungol_only_degrades_the_card(
    client: TestClient, live_mode: None, fake_adapters: dict[str, bool], monkeypatch
):
    async def dead_jungol(handle: str, **_: Any) -> JungOlSnapshot:
        return JungOlSnapshot(
            status=PlatformStatus.UNAVAILABLE,
            fetched_at=_TS,
            note="user not found",
            handle=handle,
            tier=0,
            rating=0,
            solved_count=0,
        )

    monkeypatch.setattr(service, "fetch_jungol", dead_jungol)
    res = client.get(
        "/api/summary.json", params={"github": "octocat", "boj": "baek", "jungol": "ghost"}
    )
    data = res.json()
    assert data["overallStatus"] == "partial"
    assert data["snapshots"]["jungol"]["status"] == "unavailable"
    # The judges that worked are untouched.
    assert data["snapshots"]["solvedac"]["handle"] == "baek"


def test_live_jungol_gets_its_own_cache_key_segment(
    client: TestClient, live_mode: None, fake_adapters: dict[str, bool]
):
    # Two profiles differing only in the jungol handle must not collide.
    from codemaru.models.input import ProfileInput

    without = service._cache_key(ProfileInput(github="octocat"))
    with_jungol = service._cache_key(ProfileInput(github="octocat", jungol="jo"))
    assert without != with_jungol
    # Handles are joined in registry order and always emitted, even when unset.
    assert without.endswith("octocat|||")
    assert with_jungol.endswith("octocat|||jo")
