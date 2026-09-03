import time

import pytest

from codemaru import service
from codemaru.cache import InMemoryCache
from codemaru.fixtures import demo
from codemaru.models.input import ProfileInput


def test_in_memory_cache_set_get_expiry_clear():
    cache = InMemoryCache()
    cache.set("k", "v", ttl_seconds=60)
    assert cache.get("k") == "v"
    cache.set("expired", "v", ttl_seconds=0)
    time.sleep(0.001)
    assert cache.get("expired") is None
    cache.clear()
    assert cache.get("k") is None


def test_in_memory_cache_reports_its_size():
    # /api/health surfaces this as a "is this instance warm?" signal.
    cache = InMemoryCache()
    assert len(cache) == 0
    cache.set("a", "1", ttl_seconds=60)
    cache.set("b", "2", ttl_seconds=60)
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0


def test_in_memory_cache_stays_under_its_cap():
    # A long-lived serverless instance would otherwise grow one entry per distinct
    # handle ever requested — a slow leak a scraper could drive.
    cache = InMemoryCache(max_entries=4)
    for i in range(20):
        cache.set(f"k{i}", str(i), ttl_seconds=60)
    assert len(cache) <= 4


def test_in_memory_cache_evicts_expired_entries_before_live_ones():
    cache = InMemoryCache(max_entries=3)
    cache.set("dead", "x", ttl_seconds=0)
    cache.set("live1", "a", ttl_seconds=60)
    cache.set("live2", "b", ttl_seconds=60)
    time.sleep(0.001)

    cache.set("fresh", "c", ttl_seconds=60)  # full -> evict

    # The expired entry is reclaimed first, so both live entries survive.
    assert cache.get("dead") is None
    assert cache.get("live1") == "a"
    assert cache.get("live2") == "b"
    assert cache.get("fresh") == "c"


def test_in_memory_cache_evicts_oldest_when_nothing_is_expired():
    cache = InMemoryCache(max_entries=2)
    cache.set("first", "1", ttl_seconds=60)
    cache.set("second", "2", ttl_seconds=60)

    cache.set("third", "3", ttl_seconds=60)

    assert cache.get("first") is None  # oldest write dropped
    assert cache.get("second") == "2"
    assert cache.get("third") == "3"


def test_in_memory_cache_overwrite_does_not_grow_the_store():
    cache = InMemoryCache(max_entries=2)
    cache.set("k", "1", ttl_seconds=60)
    cache.set("k", "2", ttl_seconds=60)
    assert len(cache) == 1
    assert cache.get("k") == "2"


async def test_get_summary_uses_cache(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}
    real = demo.resolve_fixture_bundle

    def counting(profile: ProfileInput):
        calls["n"] += 1
        return real(profile)

    monkeypatch.setattr(service, "resolve_fixture_bundle", counting)
    service.clear_cache()

    profile = ProfileInput(github="octocat", boj="baek")
    first = await service.get_summary(profile)
    second = await service.get_summary(profile)

    assert calls["n"] == 1  # second call served from cache
    assert first == second


async def test_get_summary_distinct_profiles_build_separately(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}
    real = demo.resolve_fixture_bundle

    def counting(profile: ProfileInput):
        calls["n"] += 1
        return real(profile)

    monkeypatch.setattr(service, "resolve_fixture_bundle", counting)
    service.clear_cache()

    await service.get_summary(ProfileInput(github="octocat"))
    await service.get_summary(ProfileInput(github="torvalds"))
    assert calls["n"] == 2
