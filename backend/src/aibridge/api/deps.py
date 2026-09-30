"""FastAPI dependency helpers."""

from __future__ import annotations

from starlette.requests import HTTPConnection

from aibridge.api.bus import EventBus
from aibridge.application.services import (
    ContextService,
    DoctorService,
    MemoryService,
    ProjectService,
    RunService,
)
from aibridge.bootstrap import Application


def get_application(connection: HTTPConnection) -> Application:
    """Retrieve the shared Application from app state."""
    return connection.app.state.application  # type: ignore[no-any-return]


def get_projects(connection: HTTPConnection) -> ProjectService:
    return get_application(connection).projects


def get_memories(connection: HTTPConnection) -> MemoryService:
    return get_application(connection).memories


def get_contexts(connection: HTTPConnection) -> ContextService:
    return get_application(connection).contexts


def get_runs(connection: HTTPConnection) -> RunService:
    return get_application(connection).runs


def get_doctor(connection: HTTPConnection) -> DoctorService:
    return get_application(connection).doctor


def get_bus(connection: HTTPConnection) -> EventBus:
    return connection.app.state.bus  # type: ignore[no-any-return]
