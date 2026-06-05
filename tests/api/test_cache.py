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
