"""FastAPI application factory for AI Bridge local control plane."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from aibridge.api.bus import EventBus
from aibridge.api.routers import candidates, health, memory, projects, runs, ws
from aibridge.api.schemas import ErrorResponse
from aibridge.bootstrap import create_application
from aibridge.config import Settings
from aibridge.errors import AIBridgeError, CandidateStateError, RepositoryError

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


def _error_status(error: AIBridgeError) -> int:
    if isinstance(error, LookupError):
        return 404
    if isinstance(error, CandidateStateError):
        return 409
    if isinstance(error, RepositoryError):
        return 500
    return 400


async def _handle_aibridge_error(_: Request, error: Exception) -> JSONResponse:
    """Return the same stable code the CLI prints as ``error[code]``."""
    coded = cast(AIBridgeError, error)
    body = ErrorResponse(code=coded.code, detail=str(coded))
    return JSONResponse(status_code=_error_status(coded), content=body.model_dump())


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
    app.add_exception_handler(AIBridgeError, _handle_aibridge_error)

    # Mount /v1 routers
    _v1_prefix = "/v1"
    error_responses: dict[int | str, dict[str, object]] = {
        400: {"model": ErrorResponse, "description": "Rejected input"},
        404: {"model": ErrorResponse, "description": "Unknown project, memory, candidate or run"},
        409: {"model": ErrorResponse, "description": "Candidate was already reviewed"},
        500: {"model": ErrorResponse, "description": "Local storage failed"},
    }
    app.include_router(health.router, prefix=_v1_prefix)
    app.include_router(projects.router, prefix=_v1_prefix, responses=error_responses)
    app.include_router(memory.router, prefix=_v1_prefix, responses=error_responses)
    app.include_router(candidates.router, prefix=_v1_prefix, responses=error_responses)
    app.include_router(runs.router, prefix=_v1_prefix, responses=error_responses)
    app.include_router(ws.router, prefix=_v1_prefix)

    # Serve built React shell from web/dist if present
    web_dist = _WEB_DIST
    if web_dist.exists() and web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="static")

    return app
