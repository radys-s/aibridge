"""Read-only run inspection while the durable task worker is not implemented."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from aibridge.api.deps import get_application, get_runs
from aibridge.api.schemas import StartRunRequest
from aibridge.application.services import RunService
from aibridge.bootstrap import Application
from aibridge.domain.models import RunRecord
from aibridge.errors import AIBridgeError

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunRecord])
async def list_runs(
    project_path: Annotated[str, Query(description="Registered project path")],
    application: Annotated[Application, Depends(get_application)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[RunRecord]:
    try:
        project = await asyncio.to_thread(
            application.repository.find_project_by_path, Path(project_path)
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        rows = await asyncio.to_thread(
            application.repository.list_runs,
            project_id=project.id,
            limit=limit,
        )
        return list(rows)
    except AIBridgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{run_id}", response_model=RunRecord)
async def get_run(
    run_id: str,
    runs: Annotated[RunService, Depends(get_runs)],
) -> RunRecord:
    try:
        return await asyncio.to_thread(runs.show, run_id)
    except AIBridgeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("")
async def start_run(_: StartRunRequest) -> None:
    """Reject unsafe execution until Phase 3 has a durable task worker."""
    raise HTTPException(
        status_code=501,
        detail={
            "code": "phase_not_ready",
            "message": "Submitting API runs requires the durable task worker from Phase 3.",
        },
    )
