"""FastAPI application factory for AI Bridge local control plane."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from aibridge.api.bus import EventBus
from aibridge.api.routers import candidates, health, memory, projects, runs, ws
from aibridge.bootstrap import create_application
from aibridge.config import Settings

_WEB_DIST = Path(__file__).parent.parent.parent.parent.parent.parent / "web" / "dist"


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize Application and EventBus, tear down cleanly on shutdown."""
    settings: Settings = app.state.settings
    application = create_application(settings)
    bus = EventBus()
    app.state.application = application
    app.state.bus = bus
    yield
    # Graceful shutdown: close DB connection pool if implemented
    if hasattr(application.repository, "close"):
        application.repository.close()


def create_api_app(settings: Settings | None = None) -> FastAPI:
    """Callable factory used by uvicorn ``--factory`` flag."""
    resolved = settings or Settings.load()

    app = FastAPI(
        title="AI Bridge",
        description="Local-first shared memory and control plane for AI agents",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )
    app.state.settings = resolved

    # Mount /v1 routers
    _v1_prefix = "/v1"
    app.include_router(health.router, prefix=_v1_prefix)
    app.include_router(projects.router, prefix=_v1_prefix)
    app.include_router(memory.router, prefix=_v1_prefix)
    app.include_router(candidates.router, prefix=_v1_prefix)
    app.include_router(runs.router, prefix=_v1_prefix)
    app.include_router(ws.router, prefix=_v1_prefix)

    # Serve built React shell from web/dist if present
    web_dist = _WEB_DIST
    if web_dist.exists() and web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="static")

    return app
