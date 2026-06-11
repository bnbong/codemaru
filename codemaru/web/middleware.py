"""ASGI middleware: security response headers and a Cloudflare-origin guard.

Both are pure ASGI (no ``BaseHTTPMiddleware``) so they never buffer the response
body or interfere with the ``record_embed`` background task on card responses.
"""

from __future__ import annotations

import hmac

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Generator page: same-origin everything, plus Google Fonts (the only external
# dependency). Keep in sync with templates/index.html.
_HTML_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

# Card SVGs reference no scripts or external resources (text is baked to vector
# paths); the shields.io-style policy is pure defense-in-depth for direct opens.
_SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'"


class SecurityHeadersMiddleware:
    """Add hardening headers to every response, tuned by content type."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message["headers"])
                content_type = headers.get("content-type", "")
                headers["X-Content-Type-Options"] = "nosniff"
                if content_type.startswith("text/html"):
                    headers["Content-Security-Policy"] = _HTML_CSP
                    headers["X-Frame-Options"] = "DENY"
                    headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                elif "image/svg+xml" in content_type:
                    headers["Content-Security-Policy"] = _SVG_CSP
            await send(message)

        await self.app(scope, receive, send_with_headers)


class OriginGuardMiddleware:
    """Reject requests that did not pass through the Cloudflare proxy.

    When ``secret`` is set, a Cloudflare *request*-header Transform Rule must
    inject ``X-Origin-Auth: <secret>`` on every request; the app then refuses any
    request lacking the matching header. Since only Cloudflare knows the secret,
    this blocks direct hits on the raw ``*.vercel.app`` origin (which skip the WAF
    / rate limiting) — and, unlike a Host-name check, it can't be defeated by
    spoofing the Host header. Disabled when ``secret`` is empty, so set it ONLY in
    the production environment (leave Preview/Dev blank to keep them reachable),
    and deploy the Cloudflare rule first so live traffic always carries the header.
    """

    def __init__(self, app: ASGIApp, secret: str | None = None) -> None:
        self.app = app
        self.secret = secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.secret:
            provided = Headers(scope=scope).get("x-origin-auth", "")
            if not hmac.compare_digest(provided, self.secret):
                response = PlainTextResponse("Forbidden", status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
