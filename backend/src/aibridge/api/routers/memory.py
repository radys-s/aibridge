"""GET /v1/memory, GET /v1/memory/{id}, POST /v1/memory."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from aibridge.api.deps import get_memories
from aibridge.api.schemas import AddMemoryRequest
from aibridge.application.services import MemoryService
from aibridge.domain.models import MemoryItem, MemoryPage, MemoryStatus
from aibridge.errors import AIBridgeError

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("", response_model=MemoryPage)
async def list_memory(
    project_path: Annotated[str, Query(description="Registered project path")],
    memories: Annotated[MemoryService, Depends(get_memories)],
    status: Annotated[MemoryStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query()] = None,
) -> MemoryPage:
    try:
        return await asyncio.to_thread(
            memories.list,
            project_path=Path(project_path),
            status=status,
            limit=limit,
            cursor=cursor,
        )
    except AIBridgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{memory_id}", response_model=MemoryItem)
async def get_memory(
    memory_id: str,
    memories: Annotated[MemoryService, Depends(get_memories)],
) -> MemoryItem:
    try:
        return await asyncio.to_thread(memories.show, memory_id)
    except AIBridgeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("", response_model=MemoryItem, status_code=201)
async def add_memory(
    body: AddMemoryRequest,
    memories: Annotated[MemoryService, Depends(get_memories)],
) -> MemoryItem:
    try:
        return await asyncio.to_thread(
            memories.add,
            project_path=Path(body.project_path),
            kind=body.kind,
            title=body.title,
            content=body.content,
            scope=body.scope,
            subject_key=body.subject_key,
            importance=body.importance,
            volatility=body.volatility,
            confidence=body.confidence,
            pinned=body.pinned,
        )
    except AIBridgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
