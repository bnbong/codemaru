"""FastAPI routes: the generator page and the card/summary/health endpoints."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from codemaru import __version__, kv
from codemaru.analytics import is_camo, record_embed, usage_count
from codemaru.core.scoring import SCORE_VERSION
from codemaru.fixtures.demo import DEMO_INPUT
from codemaru.models.render import RenderOptions, ThemeName
from codemaru.models.score import Tier
from codemaru.models.snapshot import PlatformStatus
from codemaru.models.summary import CodemaruSummary
from codemaru.render import render_card, render_error_card
from codemaru.render.themes import TIER_COLORS
from codemaru.service import cache_size, effective_mode, get_summary
from codemaru.settings import get_settings
from codemaru.telemetry import log_exception
from codemaru.web.query import QueryError, parse_request
from codemaru.web.snippets import ACTION_AVAILABLE, build_card_query, build_snippets

BASE_DIR = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

_SVG_MEDIA = "image/svg+xml; charset=utf-8"
_JSON_MEDIA = "application/json; charset=utf-8"

# Adoption badge tint — the Maru (top tier) accent, as a shields hex (no '#').
_BADGE_COLOR = TIER_COLORS[Tier.MARU].lstrip("#")


# Truthy spellings accepted by web/query.py. Reused here for params parsed
# *outside* the validated path (the error-card layout, the health deep probe),
# where an unrecognized value must degrade quietly rather than raise.
_TRUTHY = {"true", "1", "yes", "on"}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def _cache_headers(body: bytes, summary: CodemaruSummary) -> dict[str, str]:
    """Browser + Vercel CDN cache headers with a content-hash ETag.

    A degraded summary — a platform that failed, or a stale-fallback copy served
    during an outage — gets a much shorter TTL. The full hour at the CDN would
    otherwise keep serving the degraded card long after the platform recovered,
    since nothing purges the edge entry.
    """
    etag = '"' + hashlib.md5(body).hexdigest() + '"'  # noqa: S324 (non-crypto use)
    if summary.stale or summary.overall_status is not PlatformStatus.OK:
        return {
            "Cache-Control": "public, max-age=60",
            "CDN-Cache-Control": "public, s-maxage=60, stale-while-revalidate=300",
            "Vercel-CDN-Cache-Control": "public, s-maxage=60, stale-while-revalidate=300",
            "ETag": etag,
        }
    cdn = "public, s-maxage=3600, stale-while-revalidate=86400"
    return {
        "Cache-Control": "public, max-age=300",
        "CDN-Cache-Control": cdn,
        "Vercel-CDN-Cache-Control": cdn,
        "ETag": etag,
    }


def _base_url(request: Request) -> str:
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def _error_card(message: str, theme: str | None, compact: str | None = None) -> Response:
    """Render an SVG error card with HTTP 200.

    GitHub's image proxy (Camo) and many CDNs won't display a non-2xx image, so
    a 4xx here would surface as a broken image in a README instead of the
    "visible error card" we want. The X-Codemaru-Error header lets API clients
    still distinguish the error, and no-store keeps it out of caches.

    Theme and compact are parsed leniently (never re-raising) so the card keeps
    the requested dimensions — a compact embed reserves 250x270, and a 640x300
    error card there would blow out the README layout.
    """
    options = RenderOptions(theme=_safe_theme(theme), compact=_truthy(compact))
    svg = render_error_card(message, options=options)
    return Response(
        svg,
        status_code=200,
        media_type=_SVG_MEDIA,
        headers={"X-Codemaru-Error": "true", "Cache-Control": "no-store"},
    )


@router.get("/api/health")
async def health(deep: str | None = None) -> JSONResponse:
    """Liveness plus the deploy facts needed to diagnose a bad environment.

    Only ever reports whether a secret is *present*, never its value. The KV
    round-trip is opt-in (``?deep=true``): uptime monitors poll the plain
    endpoint, and a KV outage must not page anyone when card rendering is fine
    without it.
    """
    settings = get_settings()
    payload: dict[str, Any] = {
        "status": "ok",
        "mode": effective_mode(),
        "scoreVersion": SCORE_VERSION,
        "version": __version__,
        "kv": "configured" if kv.credentials() is not None else "unconfigured",
        "githubToken": "configured" if settings.github_token else "unconfigured",
        "cacheEntries": cache_size(),
    }
    if _truthy(deep):
        payload["kvPing"] = await _kv_ping()
    return JSONResponse(payload)


async def _kv_ping() -> str:
    """Best-effort KV round-trip for ``/api/health?deep=true``."""
    creds = kv.credentials()
    if creds is None:
        return "unconfigured"
    try:
        # kv.command's client carries this timeout already; the wait_for is a
        # hard ceiling so a hung connection can't stall the health check.
        await asyncio.wait_for(
            kv.command(*creds, "PING"), timeout=get_settings().kv_timeout_seconds
        )
    except Exception:  # noqa: BLE001 - a health probe reports failures, never raises
        return "error"
    return "ok"


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    """Browsers auto-request /favicon.ico at the root; point it at the logo."""
    return RedirectResponse("/static/codemaru_logo.png", status_code=308)


@router.get("/api/card.svg")
async def card_svg(
    request: Request,
    github: str | None = None,
    boj: str | None = None,
    leetcode: str | None = None,
    jungol: str | None = None,
    theme: str | None = None,
    compact: str | None = None,
    animate: str | None = None,
) -> Response:
    try:
        profile, options = parse_request(
            github, boj, leetcode, jungol, theme=theme, compact=compact, animate=animate
        )
    except QueryError as exc:
        return _error_card(str(exc), theme, compact)

    try:
        summary = await get_summary(profile)
        svg = render_card(summary, options)
    except Exception:  # noqa: BLE001 - see below; a card must never 500
        # Anything unexpected here (an adapter bug, the KV client, a renderer
        # edge case) would surface as a FastAPI 500, and a non-2xx image is a
        # broken image in someone's README. Show the error card instead, uncached
        # so the next request retries. summary.json deliberately does NOT do this
        # — a JSON 500 there is honest and easier to debug.
        #
        # The card hides the reason from the viewer, so log it with a traceback:
        # otherwise this branch swallows real bugs silently.
        log_exception("card_error", handle=profile.github)
        return _error_card("temporarily unavailable", theme, compact)

    body = svg.encode("utf-8")
    # A fetch from GitHub's image proxy (Camo) means the card is really rendered
    # in someone's README. For those: cache the response at the CDN (for viewers)
    # and record the embed in the BACKGROUND — it runs after the body is flushed,
    # so it never delays the response. Non-Camo hits (generator preview, opening
    # the URL directly) are served `no-store` so they can't populate the shared
    # CDN entry and shadow the Camo request that does the counting.
    if is_camo(request.headers.get("user-agent")):
        # Only count handles backed by real GitHub data. A spoofed `User-Agent:
        # camo` to a non-existent handle (live mode -> github snapshot
        # `unavailable`) would otherwise let anyone inflate the badge and grow
        # the KV set without bound. In fixture mode the snapshot is always usable.
        gh = summary.snapshots.github
        background = (
            BackgroundTask(record_embed, profile.github) if gh is not None and gh.usable else None
        )
        return Response(
            body,
            media_type=_SVG_MEDIA,
            headers=_cache_headers(body, summary),
            background=background,
        )
    return Response(body, media_type=_SVG_MEDIA, headers={"Cache-Control": "no-store"})


@router.get("/api/summary.json")
async def summary_json(
    github: str | None = None,
    boj: str | None = None,
    leetcode: str | None = None,
    jungol: str | None = None,
    theme: str | None = None,
    compact: str | None = None,
) -> Response:
    try:
        profile, _options = parse_request(
            github, boj, leetcode, jungol, theme=theme, compact=compact
        )
        summary = await get_summary(profile)
    except QueryError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    body = summary.model_dump_json(by_alias=True).encode("utf-8")
    return Response(body, media_type=_JSON_MEDIA, headers=_cache_headers(body, summary))


@router.get("/api/stats/badge")
async def stats_badge() -> JSONResponse:
    """A shields.io endpoint badge: distinct developers who embedded a card.

    Use in a README via
    ``https://img.shields.io/endpoint?url=<this URL>``.
    """
    count = await usage_count()
    cdn = "public, s-maxage=600, stale-while-revalidate=3600"
    return JSONResponse(
        {"schemaVersion": 1, "label": "users", "message": str(count), "color": _BADGE_COLOR},
        headers={
            "Cache-Control": "public, max-age=60",
            "CDN-Cache-Control": cdn,
            "Vercel-CDN-Cache-Control": cdn,
        },
    )


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    github: str | None = None,
    boj: str | None = None,
    leetcode: str | None = None,
    jungol: str | None = None,
    theme: str | None = None,
    compact: str | None = None,
    animate: str | None = None,
) -> HTMLResponse:
    # No github param at all → show the working demo so the first screen is a
    # live generator, not an empty form.
    if github is None:
        github, boj = DEMO_INPUT.github, DEMO_INPUT.boj
        leetcode, jungol = DEMO_INPUT.leetcode, DEMO_INPUT.jungol

    error: str | None = None
    preview_url: str | None = None
    snippets: dict[str, str] | None = None
    profile = None

    try:
        profile, options = parse_request(
            github, boj, leetcode, jungol, theme=theme, compact=compact, animate=animate
        )
        preview_url = "/api/card.svg?" + build_card_query(profile, options)
        snippets = build_snippets(_base_url(request), profile, options)
    except QueryError as exc:
        error = str(exc)
        options = RenderOptions(theme=_safe_theme(theme))

    context = {
        "request": request,
        "values": {
            "github": github or "",
            "boj": boj or "",
            "leetcode": leetcode or "",
            "jungol": jungol or "",
            "theme": options.theme.value,
            "compact": options.compact,
            # On the QueryError path `options` is a fresh RenderOptions, so the
            # animation select falls back to its default (on) rather than to the
            # value that failed validation.
            "animate": options.animate,
        },
        "themes": [t.value for t in ThemeName],
        "error": error,
        "preview_url": preview_url,
        "snippets": snippets,
        "action_available": ACTION_AVAILABLE,
        "mode": effective_mode(),
    }
    return templates.TemplateResponse(request, "index.html", context)


def _safe_theme(theme: str | None) -> ThemeName:
    try:
        return ThemeName((theme or "default").strip().lower())
    except ValueError:
        return ThemeName.DEFAULT
