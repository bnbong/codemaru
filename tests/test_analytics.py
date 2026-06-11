"""Tests for best-effort adoption tracking (codemaru.analytics)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from codemaru import analytics
from codemaru.analytics import is_camo, record_embed, usage_count


@pytest.fixture(autouse=True)
def _clear_dedupe():
    # The in-process dedupe set is module-global; reset it for deterministic tests.
    analytics._seen.clear()
    yield
    analytics._seen.clear()


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        ("github-camo/2473f9", True),
        ("Camo Asset Proxy 1.2", True),
        ("Mozilla/5.0 (Macintosh) Chrome/120", False),
        ("", False),
        (None, False),
    ],
)
def test_is_camo(user_agent: str | None, expected: bool):
    assert is_camo(user_agent) is expected


def test_credentials_present_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch):
    from codemaru import settings as settings_mod

    monkeypatch.setattr(
        analytics,
        "get_settings",
        lambda: settings_mod.Settings(
            kv_rest_api_url="https://kv.example/", kv_rest_api_token="tok"
        ),
    )
    assert analytics._credentials() == ("https://kv.example", "tok")


def test_credentials_none_when_unconfigured(monkeypatch: pytest.MonkeyPatch):
    from codemaru import settings as settings_mod

    monkeypatch.setattr(
        analytics,
        "get_settings",
        lambda: settings_mod.Settings(kv_rest_api_url=None, kv_rest_api_token=None),
    )
    assert analytics._credentials() is None


async def test_usage_count_is_zero_without_kv(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analytics, "_credentials", lambda: None)
    assert await usage_count() == 0


async def test_record_embed_is_noop_without_kv(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analytics, "_credentials", lambda: None)
    await record_embed("octocat")  # must not raise or make a request


class _FakeResp:
    def __init__(self, data: dict[str, Any], status: int = 200) -> None:
        self._data = data
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict[str, Any]:
        return self._data


class _FakeClient:
    """Records (url, json-body) of each POST; returns a canned result."""

    calls: list[tuple[str, list[str] | None]] = []
    result: Any = 7
    result_by_cmd: dict[str, Any] | None = None
    status: int = 200

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def post(
        self, url: str, json: list[str] | None = None, headers: dict[str, str] | None = None
    ) -> _FakeResp:
        _FakeClient.calls.append((url, json))
        result = _FakeClient.result
        if _FakeClient.result_by_cmd is not None and json:
            result = _FakeClient.result_by_cmd.get(json[0], _FakeClient.result)
        return _FakeResp({"result": result}, _FakeClient.status)


def _use_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: Any = 7,
    result_by_cmd: dict[str, Any] | None = None,
    status: int = 200,
) -> None:
    monkeypatch.setattr(analytics, "_credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr(analytics.httpx, "AsyncClient", _FakeClient)
    _FakeClient.calls = []
    _FakeClient.result = result
    _FakeClient.result_by_cmd = result_by_cmd
    _FakeClient.status = status


async def test_usage_count_dual_reads_hll_and_legacy_set(monkeypatch: pytest.MonkeyPatch):
    # The badge dual-reads the HLL and the legacy SET and returns the larger, so
    # it never regresses across the migration. Here the legacy SET is still ahead.
    _use_fake(monkeypatch, result_by_cmd={"PFCOUNT": 7, "SCARD": 12})
    assert await usage_count() == 12  # max(HLL 7, legacy SET 12)
    bodies = [body for _url, body in _FakeClient.calls]
    assert bodies == [["PFCOUNT", "codemaru:users:hll"], ["SCARD", "codemaru:users"]]


async def test_record_embed_sends_lowercased_handle_in_body(monkeypatch: pytest.MonkeyPatch):
    _use_fake(monkeypatch)
    await record_embed("OctoCat")
    url, body = _FakeClient.calls[0]
    assert url == "https://kv.example"
    assert body == ["PFADD", "codemaru:users:hll", "octocat"]  # HLL add, body command


async def test_record_embed_dedupes_within_instance(monkeypatch: pytest.MonkeyPatch):
    _use_fake(monkeypatch)
    await record_embed("octocat")
    await record_embed("octocat")  # same handle -> skipped
    await record_embed("torvalds")
    bodies = [body for _url, body in _FakeClient.calls]
    assert bodies == [
        ["PFADD", "codemaru:users:hll", "octocat"],
        ["PFADD", "codemaru:users:hll", "torvalds"],
    ]


async def test_record_embed_swallows_http_error(monkeypatch: pytest.MonkeyPatch):
    # A non-2xx KV response goes through raise_for_status but must not propagate.
    _use_fake(monkeypatch, status=500)
    await record_embed("octocat")  # no exception
    assert _FakeClient.calls  # the request was attempted


def test_dedupe_eviction_paths(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(analytics, "_DEDUPE_MAX", 2)
    analytics._seen.clear()
    analytics._seen["old"] = 0.0  # expiry 0 < monotonic() -> expired

    assert analytics._seen_recently("a") is False  # under cap, just marks
    assert analytics._seen_recently("b") is False  # at cap -> evicts the expired "old"
    assert "old" not in analytics._seen

    # "a" and "b" are now both unexpired; the next insert can't evict, so it
    # hard-resets the set, then records "c".
    assert analytics._seen_recently("c") is False
    assert "c" in analytics._seen
    assert "a" not in analytics._seen


async def test_usage_count_swallows_errors(monkeypatch: pytest.MonkeyPatch):
    class _Boom:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> _Boom:
            raise RuntimeError("network down")

        async def __aexit__(self, *a: Any) -> bool:
            return False

    monkeypatch.setattr(analytics, "_credentials", lambda: ("https://kv.example", "tok"))
    monkeypatch.setattr(analytics.httpx, "AsyncClient", _Boom)
    assert await usage_count() == 0
