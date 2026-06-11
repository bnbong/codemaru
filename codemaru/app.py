"""FastAPI application factory and module-level ``app`` for ASGI servers/Vercel."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from codemaru import __version__
from codemaru.settings import get_settings
from codemaru.web.middleware import OriginGuardMiddleware, SecurityHeadersMiddleware
from codemaru.web.routes import router

BASE_DIR = Path(__file__).resolve().parents[1]


def create_app() -> FastAPI:
    app = FastAPI(
        title="codemaru",
        description="Developer programming-activity summary cards for GitHub READMEs.",
        version=__version__,
    )
    # Added inner-first: OriginGuard runs nearest the app (rejects bypass
    # traffic), SecurityHeaders is outermost so even a 403 carries `nosniff`.
    app.add_middleware(OriginGuardMiddleware, secret=get_settings().origin_shared_secret)
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.include_router(router)
    return app


app = create_app()
