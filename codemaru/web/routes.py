"""FastAPI routes: the generator page and the card/summary/health endpoints."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from codemaru.core.scoring import SCORE_VERSION
from codemaru.fixtures.demo import DEMO_INPUT
from codemaru.models.render import RenderOptions, ThemeName
from codemaru.render import render_card, render_error_card
from codemaru.service import LiveDataUnavailableError, effective_mode, get_summary
from codemaru.settings import get_settings
from codemaru.web.query import QueryError, parse_request
from codemaru.web.snippets import ACTION_AVAILABLE, build_card_query, build_snippets

BASE_DIR = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

_SVG_MEDIA = "image/svg+xml; charset=utf-8"
_JSON_MEDIA = "application/json; charset=utf-8"


def _cache_headers(body: bytes) -> dict[str, str]:
    """Browser + Vercel CDN cache headers with a content-hash ETag."""
    etag = '"' + hashlib.md5(body).hexdigest() + '"'  # noqa: S324 (non-crypto use)
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


def _error_card(message: str, theme: str | None) -> Response:
    """Render an SVG error card with HTTP 200.

    GitHub's image proxy (Camo) and many CDNs won't display a non-2xx image, so
    a 4xx here would surface as a broken image in a README instead of the
    "visible error card" we want. The X-Codemaru-Error header lets API clients
    still distinguish the error, and no-store keeps it out of caches.
    """
    svg = render_error_card(message, options=RenderOptions(theme=_safe_theme(theme)))
    return Response(
        svg,
        status_code=200,
        media_type=_SVG_MEDIA,
        headers={"X-Codemaru-Error": "true", "Cache-Control": "no-store"},
    )


@router.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "mode": effective_mode(),
            "scoreVersion": SCORE_VERSION,
        }
    )


@router.get("/api/card.svg")
def card_svg(
    request: Request,
    github: str | None = None,
    boj: str | None = None,
    leetcode: str | None = None,
    theme: str | None = None,
    compact: str | None = None,
) -> Response:
    try:
        profile, options = parse_request(github, boj, leetcode, theme, compact)
        summary = get_summary(profile)
    except (QueryError, LiveDataUnavailableError) as exc:
        return _error_card(str(exc), theme)

    svg = render_card(summary, options)
    body = svg.encode("utf-8")
    return Response(body, media_type=_SVG_MEDIA, headers=_cache_headers(body))


@router.get("/api/summary.json")
def summary_json(
    github: str | None = None,
    boj: str | None = None,
    leetcode: str | None = None,
    theme: str | None = None,
    compact: str | None = None,
) -> Response:
    try:
        profile, _options = parse_request(github, boj, leetcode, theme, compact)
        summary = get_summary(profile)
    except QueryError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except LiveDataUnavailableError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)

    body = summary.model_dump_json(by_alias=True).encode("utf-8")
    return Response(body, media_type=_JSON_MEDIA, headers=_cache_headers(body))


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    github: str | None = None,
    boj: str | None = None,
    leetcode: str | None = None,
    theme: str | None = None,
    compact: str | None = None,
) -> HTMLResponse:
    # No github param at all → show the working demo so the first screen is a
    # live generator, not an empty form.
    if github is None:
        github, boj, leetcode = DEMO_INPUT.github, DEMO_INPUT.boj, DEMO_INPUT.leetcode

    error: str | None = None
    preview_url: str | None = None
    snippets: dict[str, str] | None = None
    profile = None

    try:
        profile, options = parse_request(github, boj, leetcode, theme, compact)
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
            "theme": options.theme.value,
            "compact": options.compact,
        },
        "themes": [t.value for t in ThemeName],
        "error": error,
        "preview_url": preview_url,
        "snippets": snippets,
        "action_available": ACTION_AVAILABLE,
    }
    return templates.TemplateResponse(request, "index.html", context)


def _safe_theme(theme: str | None) -> ThemeName:
    try:
        return ThemeName((theme or "default").strip().lower())
    except ValueError:
        return ThemeName.DEFAULT
