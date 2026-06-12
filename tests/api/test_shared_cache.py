"""Shared summary cache backed by Vercel KV (Upstash) — exercised without a
network by monkeypatching ``codemaru.kv``."""

from __future__ import annotations

from typing import Any

import pytest

from codemaru import service
from codemaru.fixtures import demo
from codemaru.models.input import ProfileInput


class _FakeKV:
    """An in-process stand-in for the Upstash REST endpoint (GET/SET + EX)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.calls: list[tuple[str, ...]] = []

    async def command(self, base: str, token: str, *args: str) -> Any:
        self.calls.append(args)
        op = args[0].upper()
        if op == "GET":
            return self.store.get(args[1])
        if op == "SET":  # SET key value EX ttl
            self.store[args[1]] = args[2]
            return "OK"
        return None


def _use_fake_kv(monkeypatch: pytest.MonkeyPatch) -> _FakeKV:
    fake = _FakeKV()
    monkeypatch.setattr("codemaru.kv.credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr("codemaru.kv.command", fake.command)
    return fake


async def test_summary_cache_is_shared_via_kv(monkeypatch: pytest.MonkeyPatch):
    fake = _use_fake_kv(monkeypatch)

    calls = {"n": 0}
    real = demo.resolve_fixture_bundle

    def counting(profile: ProfileInput):
        calls["n"] += 1
        return real(profile)

    monkeypatch.setattr(service, "resolve_fixture_bundle", counting)
    service.clear_cache()  # in-memory stores are unused on the KV path

    profile = ProfileInput(github="octocat", boj="baek")
    first = await service.get_summary(profile)
    second = await service.get_summary(profile)

    assert calls["n"] == 1  # second call served from the shared KV, not rebuilt
    assert first == second
    # The summary was written to KV under the versioned profile key, with a TTL.
    assert any(c[0] == "SET" and c[1].startswith("summary:") and "EX" in c for c in fake.calls)
    assert any(k.startswith("summary:") for k in fake.store)


async def test_kv_failure_falls_back_to_rebuild(monkeypatch: pytest.MonkeyPatch):
    async def boom(*_args: Any) -> Any:
        raise RuntimeError("kv down")

    monkeypatch.setattr("codemaru.kv.credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr("codemaru.kv.command", boom)
    monkeypatch.setattr(service, "resolve_fixture_bundle", demo.resolve_fixture_bundle)
    service.clear_cache()

    # Every KV call raises, but rendering must never break — it just rebuilds.
    summary = await service.get_summary(ProfileInput(github="octocat"))
    assert summary.scores.tier is not None


async def test_kv_outage_uses_in_memory_mirror_not_rebuild(monkeypatch: pytest.MonkeyPatch):
    # With KV configured but failing, a successful build is mirrored into the
    # in-memory cache, so a warm instance serves the second request from memory
    # instead of doing a fresh live build every time.
    async def boom(*_args: Any) -> Any:
        raise RuntimeError("kv down")

    monkeypatch.setattr("codemaru.kv.credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr("codemaru.kv.command", boom)

    calls = {"n": 0}
    real = demo.resolve_fixture_bundle

    def counting(profile: ProfileInput):
        calls["n"] += 1
        return real(profile)

    monkeypatch.setattr(service, "resolve_fixture_bundle", counting)
    service.clear_cache()

    profile = ProfileInput(github="octocat")
    await service.get_summary(profile)
    await service.get_summary(profile)
    assert calls["n"] == 1  # second served from the in-memory mirror despite KV being down


async def test_remote_miss_falls_back_to_in_memory_mirror(monkeypatch: pytest.MonkeyPatch):
    # KV is up, but the remote entry isn't there (an earlier SET didn't persist or
    # was evicted) while this instance still holds a valid mirror. A remote nil
    # must NOT discard the mirror and force a rebuild on every request.
    async def write_drop(_base: str, _token: str, *args: str) -> Any:
        return None if args[0].upper() == "GET" else "OK"  # GET always nil, SET no-ops

    monkeypatch.setattr("codemaru.kv.credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr("codemaru.kv.command", write_drop)

    calls = {"n": 0}
    real = demo.resolve_fixture_bundle

    def counting(profile: ProfileInput):
        calls["n"] += 1
        return real(profile)

    monkeypatch.setattr(service, "resolve_fixture_bundle", counting)
    service.clear_cache()

    profile = ProfileInput(github="octocat")
    await service.get_summary(profile)
    await service.get_summary(profile)
    assert calls["n"] == 1  # second served from the mirror despite the remote nil


async def test_corrupt_cache_entry_is_treated_as_miss(monkeypatch: pytest.MonkeyPatch):
    # A shared cache means a cached payload is now external input — an entry from
    # a different deploy's schema must NOT 500; it falls through to a rebuild
    # (which overwrites it), not an uncaught ValidationError.
    monkeypatch.setattr(service, "resolve_fixture_bundle", demo.resolve_fixture_bundle)
    service.clear_cache()
    profile = ProfileInput(github="octocat")
    service._cache.set(service._cache_key(profile), '{"unexpected":"schema"}', 60)

    summary = await service.get_summary(profile)  # must not raise
    assert summary.input.github == "octocat"


def test_cache_key_scopes_mode_and_omits_none():
    # LOW-1: an unset handle serializes to "" (not "None"), and a real handle
    # named "None" gets a distinct key. The key is also scoped by mode.
    bare = service._cache_key(ProfileInput(github="octocat"))
    assert "None" not in bare
    assert ":fixture:" in bare  # tests run in fixture mode
    named_none = service._cache_key(ProfileInput(github="octocat", boj="None"))
    assert bare != named_none
