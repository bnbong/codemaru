"""Security-headers and Cloudflare-origin-guard middleware."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from codemaru.app import create_app
from codemaru.settings import get_settings
from codemaru.web.middleware import SecurityHeadersMiddleware


def test_html_has_security_headers(client: TestClient):
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    csp = res.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    # Parse into directives and assert the font-src value exactly. (Comparing the
    # whole directive — not a `"<url>" in csp` substring check — also keeps CodeQL
    # from flagging this as incomplete-URL-substring sanitization.)
    directives = {part.split()[0]: part.strip() for part in csp.split(";") if part.strip()}
    # The only external origin the generator needs is Google Fonts.
    assert directives["font-src"] == "font-src 'self' https://fonts.gstatic.com"


def test_svg_has_locked_down_csp(client: TestClient):
    res = client.get("/api/card.svg", params={"github": "octocat"})
    assert res.status_code == 200
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'"


def test_json_gets_nosniff_only(client: TestClient):
    res = client.get("/api/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in res.headers  # CSP only for html/svg


def _client_with_secret(monkeypatch: pytest.MonkeyPatch, secret: str) -> TestClient:
    monkeypatch.setenv("FIXTURE_MODE", "true")
    monkeypatch.setenv("ORIGIN_SHARED_SECRET", secret)
    get_settings.cache_clear()
    # The guard captures the secret at app construction, so build a fresh app.
    return TestClient(create_app())


def test_origin_guard_blocks_request_without_header(monkeypatch: pytest.MonkeyPatch):
    # No X-Origin-Auth -> a request that didn't pass through Cloudflare -> 403.
    client = _client_with_secret(monkeypatch, "s3cret")
    res = client.get("/api/health")
    assert res.status_code == 403
    # SecurityHeaders is the outermost middleware, so even a guard rejection still
    # carries nosniff — this locks in that ordering against future regressions.
    assert res.headers["x-content-type-options"] == "nosniff"


def test_origin_guard_allows_request_with_correct_header(monkeypatch: pytest.MonkeyPatch):
    client = _client_with_secret(monkeypatch, "s3cret")
    res = client.get("/api/health", headers={"x-origin-auth": "s3cret"})
    assert res.status_code == 200


def test_origin_guard_blocks_wrong_header(monkeypatch: pytest.MonkeyPatch):
    client = _client_with_secret(monkeypatch, "s3cret")
    res = client.get("/api/health", headers={"x-origin-auth": "wrong"})
    assert res.status_code == 403


def test_origin_guard_disabled_when_no_secret(client: TestClient):
    # Default app (no ORIGIN_SHARED_SECRET): the check is off, all requests pass.
    assert client.get("/api/health").status_code == 200


async def test_security_headers_passes_through_non_http_scope():
    # Non-HTTP scopes (lifespan / websocket) must be forwarded untouched — the
    # header logic only applies to http responses.
    seen: dict[str, Any] = {}

    async def downstream(scope: Any, receive: Any, send: Any) -> None:
        seen["type"] = scope["type"]

    async def _recv() -> dict[str, Any]:
        return {"type": "lifespan.startup"}

    async def _send(_message: dict[str, Any]) -> None:
        return None

    await SecurityHeadersMiddleware(downstream)({"type": "lifespan"}, _recv, _send)
    assert seen["type"] == "lifespan"  # forwarded to the wrapped app
