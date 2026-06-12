"""Unit tests for the shared Vercel KV (Upstash REST) helper."""

from __future__ import annotations

from typing import Any

import pytest

from codemaru import kv
from codemaru import settings as settings_mod


def test_credentials_present_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        kv,
        "get_settings",
        lambda: settings_mod.Settings(kv_rest_api_url="https://kv.example/", kv_rest_api_token="t"),
    )
    assert kv.credentials() == ("https://kv.example", "t")


def test_credentials_none_when_unconfigured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        kv,
        "get_settings",
        lambda: settings_mod.Settings(kv_rest_api_url=None, kv_rest_api_token=None),
    )
    assert kv.credentials() is None


def test_http_client_is_lazily_created_and_reused(monkeypatch: pytest.MonkeyPatch):
    created: list[dict[str, Any]] = []

    class _FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

    monkeypatch.setattr(kv.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(kv, "_client", None)  # force a fresh lazy build

    first = kv._http_client()
    second = kv._http_client()
    assert first is second  # one client reused across calls (warm connection)
    assert len(created) == 1


async def test_command_posts_array_body_and_returns_result(monkeypatch: pytest.MonkeyPatch):
    posts: list[tuple[str, Any, dict[str, str]]] = []

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"result": "PONG"}

    class _Client:
        async def post(self, url: str, json: Any = None, headers: Any = None) -> _Resp:
            posts.append((url, json, headers))
            return _Resp()

    monkeypatch.setattr(kv, "_http_client", lambda: _Client())

    result = await kv.command("https://kv.example", "tok", "GET", "mykey")
    assert result == "PONG"
    url, body, headers = posts[0]
    assert url == "https://kv.example"  # command travels in the body, not the path
    assert body == ["GET", "mykey"]
    assert headers["Authorization"] == "Bearer tok"
