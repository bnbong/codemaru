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
    # `img-src data:` is required, not optional: the tier nameplate is an embedded
    # base64 PNG, and without the directive it silently vanishes when the card URL
    # is opened directly in a browser tab.
    assert (
        res.headers["content-security-policy"]
        == "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    )


def _directives(csp: str) -> dict[str, str]:
    return {part.split()[0]: part.strip() for part in csp.split(";") if part.strip()}


def _sources(csp: str, directive: str) -> list[str]:
    """Token list for one CSP directive (e.g. the entries after ``script-src``).

    Membership checks use this instead of ``"<url>" in <csp string>`` so they
    compare whole source tokens rather than doing substring matching on a URL —
    which also keeps CodeQL from flagging this file as incomplete-URL-substring
    sanitization.
    """
    for part in csp.split(";"):
        tokens = part.split()
        if tokens and tokens[0] == directive:
            return tokens[1:]
    return []


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_docs_csp_allows_the_swagger_cdn(client: TestClient, path: str):
    # Swagger UI / ReDoc load their bundles from jsDelivr, so the generator's
    # `script-src 'self'` renders these pages blank. Assert whole directives (not
    # substrings) so a missing origin can't pass on a partial match.
    res = client.get(path)
    assert res.status_code == 200
    directives = _directives(res.headers["content-security-policy"])
    # 'unsafe-inline' is required, not incidental: FastAPI's get_swagger_ui_html
    # boots Swagger UI from an inline <script> and exposes no nonce hook, so
    # without it /docs loads the bundle and then renders a blank page.
    assert directives["script-src"] == "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
    # ReDoc also pulls Montserrat/Roboto from Google Fonts, so its stylesheet and
    # font origins ride along — the same pair the generator page already allows.
    assert directives["style-src"] == (
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com"
    )
    assert directives["font-src"] == "font-src 'self' https://fonts.gstatic.com"
    assert directives["img-src"] == "img-src 'self' data: https://fastapi.tiangolo.com"
    assert directives["connect-src"] == "connect-src 'self'"
    assert directives["frame-ancestors"] == "frame-ancestors 'none'"


def test_docs_page_actually_renders_swagger_ui(client: TestClient):
    # The header assertions above only prove the policy; this proves the route is
    # served under it — the page's inline bootstrap and the widened CSP together
    # are what make /docs non-blank.
    res = client.get("/docs")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "SwaggerUIBundle" in res.text
    assert "<script>" in res.text  # the inline bootstrap 'unsafe-inline' is for
    csp = res.headers["content-security-policy"]
    assert "'unsafe-inline'" in _sources(csp, "script-src")
    assert "https://cdn.jsdelivr.net" in _sources(csp, "script-src")


def test_generator_page_csp_is_not_widened_by_the_docs_policy(client: TestClient):
    # The docs exception is scoped to the docs paths; the generator — the one page
    # that renders user-supplied handles — keeps its strict same-origin script
    # policy, with no inline scripts allowed.
    csp = client.get("/").headers["content-security-policy"]
    directives = _directives(csp)
    assert directives["script-src"] == "script-src 'self'"
    assert "'unsafe-inline'" not in _sources(csp, "script-src")
    assert "https://cdn.jsdelivr.net" not in _sources(csp, "style-src")


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
