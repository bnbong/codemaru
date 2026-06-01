"""FastAPI application factory and module-level ``app`` for ASGI servers/Vercel."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from codemaru.web.routes import router

BASE_DIR = Path(__file__).resolve().parents[1]


def create_app() -> FastAPI:
    app = FastAPI(
        title="codemaru",
        description="Developer programming-activity summary cards for GitHub READMEs.",
        version="0.1.0",
    )
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.include_router(router)
    return app


app = create_app()
