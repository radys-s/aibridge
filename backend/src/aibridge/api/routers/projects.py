"""POST /v1/projects, GET /v1/projects, GET /v1/projects/{project_id}."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from aibridge.api.deps import get_application, get_projects
from aibridge.api.schemas import RegisterProjectRequest
from aibridge.application.services import ProjectService
from aibridge.bootstrap import Application
from aibridge.domain.models import Project
from aibridge.errors import ProjectNotRegisteredError

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=Project, status_code=201)
async def register_project(
    body: RegisterProjectRequest,
    projects: Annotated[ProjectService, Depends(get_projects)],
) -> Project:
    return await asyncio.to_thread(projects.register, Path(body.path), body.name)


@router.get("", response_model=list[Project])
async def list_projects(
    application: Annotated[Application, Depends(get_application)],
) -> list[Project]:
    rows = await asyncio.to_thread(application.repository.list_projects)
    return list(rows)


@router.get("/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    application: Annotated[Application, Depends(get_application)],
) -> Project:
    project = await asyncio.to_thread(application.repository.get_project_by_id, project_id)
    if project is None:
        raise ProjectNotRegisteredError(f"Project not found: {project_id}")
    return project
