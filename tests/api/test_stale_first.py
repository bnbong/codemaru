"""Stale-first serving: an expired card answers with its last-good copy at once
and rebuilds in the background (live mode, adapters monkeypatched)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.background import BackgroundTasks
from starlette.requests import Request

from codemaru import service, telemetry
from codemaru.models.input import ProfileInput
from codemaru.models.snapshot import GitHubSnapshot, PlatformStatus, SolvedAcSnapshot
from codemaru.settings import get_settings
from codemaru.web import routes
from tests.api.test_shared_cache import _use_fake_kv

_TS = datetime(2026, 5, 31, tzinfo=UTC)


def _github(login: str, followers: int) -> GitHubSnapshot:
    return GitHubSnapshot(
        status=PlatformStatus.OK,
        fetched_at=_TS,
        login=login,
        public_repos=10,
        total_stars=500,
        total_forks=40,
        followers=followers,
        total_commits=900,
        total_pull_requests=70,
        total_issues=30,
        total_reviews=40,
        contributed_repos=12,
        active_days=150,
        longest_streak=20,
        language_count=5,
    )


def _solvedac(handle: str, status: PlatformStatus) -> SolvedAcSnapshot:
    ok = status is PlatformStatus.OK
    return SolvedAcSnapshot(
        status=status,
        fetched_at=_TS,
        handle=handle,
        tier=12 if ok else 0,
        rating=1200 if ok else 0,
        solved_count=600 if ok else 0,
        class_level=4 if ok else 0,
    )


class _Platforms:
    """Monkeypatched adapters with a call counter and switchable data."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.github_calls = 0
        self.followers = 80
        self.solvedac_status = PlatformStatus.OK
        monkeypatch.setattr(service, "fetch_github", self.fetch_github)
        monkeypatch.setattr(service, "fetch_solvedac", self.fetch_solvedac)

    async def fetch_github(self, login: str, **_: Any) -> GitHubSnapshot:
        self.github_calls += 1
        return _github(login, self.followers)

    async def fetch_solvedac(self, handle: str, **_: Any) -> SolvedAcSnapshot:
        return _solvedac(handle, self.solvedac_status)


@pytest.fixture
def platforms(live_mode: None, monkeypatch: pytest.MonkeyPatch) -> _Platforms:
    return _Platforms(monkeypatch)


_PROFILE = ProfileInput(github="octocat", boj="baek")


async def _seed_last_good(platforms: _Platforms) -> None:
    """Build once (fills both stores), then let the response cache expire."""
    first = await service.get_summary(_PROFILE)
    assert first.stale is False
    assert first.snapshots.github is not None
    service._cache.clear()
    # The data moves on, so a refreshed summary is distinguishable from the old.
    platforms.followers = 500


def _github_followers(summary: Any) -> int:
    assert summary.snapshots.github is not None
    return int(summary.snapshots.github.followers)


def _record_ttls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture every response-cache write TTL (plain and only-if-absent) while
    still writing it."""
    ttls: list[float] = []
    real = service._cache_write
    real_nx = service._cache_write_if_absent

    async def spy(key: str, value: str, ttl_seconds: float) -> None:
        ttls.append(ttl_seconds)
        await real(key, value, ttl_seconds)

    async def spy_nx(key: str, value: str, ttl_seconds: float) -> bool:
        ttls.append(ttl_seconds)
        return await real_nx(key, value, ttl_seconds)

    monkeypatch.setattr(service, "_cache_write", spy)
    monkeypatch.setattr(service, "_cache_write_if_absent", spy_nx)
    return ttls


# --- service ---------------------------------------------------------------


async def test_miss_with_last_good_serves_stale_then_refreshes(
    platforms: _Platforms, monkeypatch: pytest.MonkeyPatch
):
    await _seed_last_good(platforms)
    calls_before = platforms.github_calls
    ttls = _record_ttls(monkeypatch)

    result = await service.get_summary_stale_first(_PROFILE)

    # Answered from the last-good store without touching the platforms.
    assert result.summary.stale is True
    assert _github_followers(result.summary) == 80
    assert platforms.github_calls == calls_before
    assert result.refresh is not None
    assert ttls == []  # nothing written on the hot path

    await result.refresh()

    settings = get_settings()
    # First the stale copy (short TTL, the cross-instance marker), then the
    # fresh build overwrites it with the full TTL.
    assert ttls == [settings.negative_cache_ttl_seconds, settings.cache_ttl_seconds]
    assert platforms.github_calls == calls_before + 1

    after = await service.get_summary_stale_first(_PROFILE)
    assert after.refresh is None  # a plain cache hit
    assert after.summary.stale is False
    assert _github_followers(after.summary) == 500

    # The last-good store now holds the fresh, non-stale summary.
    last_good = await service._read_last_good(service._cache_key(_PROFILE))
    assert last_good is not None
    assert last_good.stale is False
    assert _github_followers(last_good) == 500


async def _refresh_over_a_fresh_entry(
    platforms: _Platforms, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, Any]:
    """Serve stale, then have another writer land a fresh entry before the
    refresh runs. Returns (cache entry seen when the build starts, cache entry
    after the refresh)."""
    key = service._cache_key(_PROFILE)
    result = await service.get_summary_stale_first(_PROFILE)
    assert result.refresh is not None

    # Another instance's full rebuild lands first (fresh, full TTL).
    other = result.summary.model_copy(update={"stale": False})
    await service._cache_write(key, other.model_dump_json(), get_settings().cache_ttl_seconds)

    seen: list[Any] = []
    real_build = service._build_live

    async def observing_build(profile: ProfileInput, settings: Any) -> Any:
        raw = await service._cache_read(key)
        seen.append(service._load_summary(raw) if raw is not None else None)
        return await real_build(profile, settings)

    monkeypatch.setattr(service, "_build_live", observing_build)
    await result.refresh()

    raw_after = await service._cache_read(key)
    assert raw_after is not None
    return seen[0], service._load_summary(raw_after)


async def test_stale_prewrite_never_replaces_a_fresh_entry_in_memory(
    platforms: _Platforms, monkeypatch: pytest.MonkeyPatch
):
    await _seed_last_good(platforms)

    at_build, after = await _refresh_over_a_fresh_entry(platforms, monkeypatch)

    # The late stale pre-write left the other writer's fresh entry alone...
    assert at_build is not None
    assert at_build.stale is False
    assert _github_followers(at_build) == 80
    # ...and our own fresh build still overwrote it unconditionally.
    assert after is not None
    assert after.stale is False
    assert _github_followers(after) == 500


async def test_stale_prewrite_never_replaces_a_fresh_entry_in_kv(
    platforms: _Platforms, monkeypatch: pytest.MonkeyPatch
):
    fake = _use_fake_kv(monkeypatch)
    await _seed_last_good(platforms)
    fake.store.pop(service._cache_key(_PROFILE))  # the response entry expired in KV too

    at_build, after = await _refresh_over_a_fresh_entry(platforms, monkeypatch)

    assert at_build is not None
    assert at_build.stale is False
    assert _github_followers(at_build) == 80
    assert after is not None
    assert after.stale is False
    assert _github_followers(after) == 500
    # The pre-write went out as SET ... NX and was refused by KV.
    nx = [c for c in fake.calls if c[0] == "SET" and "NX" in c]
    assert len(nx) == 1


async def test_stale_prewrite_lands_when_kv_holds_nothing(
    platforms: _Platforms, monkeypatch: pytest.MonkeyPatch
):
    fake = _use_fake_kv(monkeypatch)
    await _seed_last_good(platforms)
    key = service._cache_key(_PROFILE)
    fake.store.pop(key)

    wrote = await service._cache_write_if_absent(key, "marker", 60)

    assert wrote is True
    assert fake.store[key] == "marker"
    assert service._cache.get(key) == "marker"  # mirror follows the KV write
    assert await service._cache_write_if_absent(key, "late", 60) is False
    assert fake.store[key] == "marker"


async def test_miss_without_last_good_builds_synchronously(platforms: _Platforms):
    result = await service.get_summary_stale_first(_PROFILE)

    assert result.refresh is None
    assert result.summary.stale is False
    assert result.summary.overall_status is PlatformStatus.OK
    assert platforms.github_calls == 1
    # ...and it seeded the last-good store for the next expiry.
    assert await service._read_last_good(service._cache_key(_PROFILE)) is not None


async def test_concurrent_misses_launch_one_refresh(platforms: _Platforms):
    await _seed_last_good(platforms)
    calls_before = platforms.github_calls

    results = await asyncio.gather(*(service.get_summary_stale_first(_PROFILE) for _ in range(5)))

    assert all(r.summary.stale for r in results)
    refreshes = [r.refresh for r in results if r.refresh is not None]
    assert len(refreshes) == 1

    await refreshes[0]()

    assert platforms.github_calls == calls_before + 1
    # The claim is released once the refresh finishes.
    assert service._cache_key(_PROFILE) not in service._refreshing


async def test_an_abandoned_claim_expires(platforms: _Platforms):
    # A claim whose refresh never ran (dropped by the caller, frozen instance)
    # must not block refreshes forever.
    await _seed_last_good(platforms)
    key = service._cache_key(_PROFILE)
    service._refreshing[key] = monotonic() - 3600

    result = await service.get_summary_stale_first(_PROFILE)

    assert result.refresh is not None


async def test_degraded_refresh_never_writes_a_stale_copy_as_last_good(
    platforms: _Platforms, monkeypatch: pytest.MonkeyPatch
):
    await _seed_last_good(platforms)
    platforms.solvedac_status = PlatformStatus.UNAVAILABLE
    stale_writes: list[str] = []
    real = service._stale_write

    async def spy(key: str, value: str, ttl_seconds: float) -> None:
        stale_writes.append(value)
        await real(key, value, ttl_seconds)

    monkeypatch.setattr(service, "_stale_write", spy)

    result = await service.get_summary_stale_first(_PROFILE)
    assert result.refresh is not None
    await result.refresh()

    # A degraded rebuild falls back to the last-good copy (stale, short TTL) and
    # leaves the last-good store alone.
    assert stale_writes == []
    cached = await service.get_summary_stale_first(_PROFILE)
    assert cached.summary.stale is True
    assert cached.summary.overall_status is PlatformStatus.OK
    last_good = await service._read_last_good(service._cache_key(_PROFILE))
    assert last_good is not None and last_good.stale is False


async def test_a_failing_refresh_is_logged_not_raised(
    platforms: _Platforms,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    await _seed_last_good(platforms)

    async def boom(profile: ProfileInput, settings: Any) -> Any:
        raise RuntimeError("adapter exploded")

    monkeypatch.setattr(service, "_build_live", boom)
    caplog.set_level(logging.ERROR, logger="codemaru")

    result = await service.get_summary_stale_first(_PROFILE)
    assert result.refresh is not None
    await result.refresh()  # must not raise

    record = next(r for r in caplog.records if r.name == "codemaru" and r.levelno >= logging.ERROR)
    payload = json.loads(telemetry.JsonLineFormatter().format(record))
    assert payload["event"] == "refresh_error"
    assert "adapter exploded" in payload["error"]
    assert payload["handle"] == "octocat"
    assert service._cache_key(_PROFILE) not in service._refreshing


async def test_fixture_mode_is_unaffected():
    # Even with something in the last-good store, fixture mode builds directly.
    key = service._cache_key(_PROFILE)
    seeded = await service.get_summary(_PROFILE)
    service._cache.clear()
    service._stale.set(
        service._STALE_PREFIX + key, seeded.model_dump_json(), get_settings().stale_ttl_seconds
    )

    result = await service.get_summary_stale_first(_PROFILE)

    assert result.refresh is None
    assert result.summary.stale is False
    assert result.summary == seeded


# --- routes ----------------------------------------------------------------


def _camo_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/card.svg",
            "query_string": b"",
            "headers": [(b"user-agent", b"github-camo/x")],
        }
    )


async def test_stale_card_response_carries_the_refresh_in_its_background(
    platforms: _Platforms, monkeypatch: pytest.MonkeyPatch
):
    await _seed_last_good(platforms)

    async def _noop(handle: str) -> None:
        return None

    monkeypatch.setattr(routes, "record_embed", _noop)

    res = await routes.card_svg(_camo_request(), github="octocat", boj="baek")

    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=60"
    assert "s-maxage=60" in res.headers["cdn-cache-control"]
    assert isinstance(res.background, BackgroundTasks)
    # Embed tracking first, then the refresh.
    funcs = [task.func for task in res.background.tasks]
    assert funcs[0] is _noop
    assert len(funcs) == 2
    assert platforms.github_calls == 1  # only the seed build so far

    await res.background()

    assert platforms.github_calls == 2
    fresh = await service.get_summary_stale_first(_PROFILE)
    assert fresh.summary.stale is False


def test_stale_card_over_http_refreshes_after_responding(
    client: TestClient, platforms: _Platforms, monkeypatch: pytest.MonkeyPatch
):
    async def _noop(handle: str) -> None:
        return None

    monkeypatch.setattr(routes, "record_embed", _noop)
    params = {"github": "octocat", "boj": "baek"}
    camo = {"User-Agent": "github-camo/x"}

    first = client.get("/api/card.svg", params=params, headers=camo)
    assert "s-maxage=3600" in first.headers["cdn-cache-control"]
    service._cache.clear()
    platforms.followers = 500

    stale = client.get("/api/card.svg", params=params, headers=camo)
    assert stale.status_code == 200
    assert "x-codemaru-error" not in stale.headers
    assert stale.headers["cache-control"] == "public, max-age=60"
    assert "s-maxage=60" in stale.headers["cdn-cache-control"]

    # TestClient runs the background before returning, so the refresh is done:
    # the next request is a fresh cache hit with the long TTL again.
    fresh = client.get("/api/card.svg", params=params, headers=camo)
    assert "s-maxage=3600" in fresh.headers["cdn-cache-control"]
    assert platforms.github_calls == 2


def test_summary_json_serves_stale_first_too(client: TestClient, platforms: _Platforms):
    params = {"github": "octocat", "boj": "baek"}
    assert client.get("/api/summary.json", params=params).json()["stale"] is False
    service._cache.clear()
    platforms.followers = 500

    stale = client.get("/api/summary.json", params=params)
    data = stale.json()
    assert data["stale"] is True
    assert data["snapshots"]["github"]["followers"] == 80
    assert stale.headers["cache-control"] == "public, max-age=60"

    fresh = client.get("/api/summary.json", params=params).json()
    assert fresh["stale"] is False
    assert fresh["snapshots"]["github"]["followers"] == 500
