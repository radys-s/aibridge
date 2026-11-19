"""Read-only run inspection while the durable task worker is not implemented."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from aibridge.api.deps import get_application, get_runs
from aibridge.api.schemas import ErrorResponse, StartRunRequest
from aibridge.application.services import RunService
from aibridge.bootstrap import Application
from aibridge.domain.models import RunRecord

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunRecord])
async def list_runs(
    project_path: Annotated[str, Query(description="Registered project path")],
    application: Annotated[Application, Depends(get_application)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[RunRecord]:
    project = await asyncio.to_thread(application.projects.require, Path(project_path))
    rows = await asyncio.to_thread(
        application.repository.list_runs,
        project_id=project.id,
        limit=limit,
    )
    return list(rows)


@router.get("/{run_id}", response_model=RunRecord)
async def get_run(
    run_id: str,
    runs: Annotated[RunService, Depends(get_runs)],
) -> RunRecord:
    return await asyncio.to_thread(runs.show, run_id)


@router.post("", status_code=501, responses={501: {"model": ErrorResponse}})
async def start_run(_: StartRunRequest) -> JSONResponse:
    """Reject unsafe execution until Phase 3 has a durable task worker."""
    body = ErrorResponse(
        code="phase_not_ready",
        detail="Submitting API runs requires the durable task worker from Phase 3.",
    )
    return JSONResponse(status_code=501, content=body.model_dump())
