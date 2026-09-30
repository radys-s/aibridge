"""GET /v1/candidates, PATCH /v1/candidates/{id}/approve, PATCH /v1/candidates/{id}/reject."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from aibridge.api.deps import get_memories
from aibridge.api.schemas import RejectCandidateRequest
from aibridge.application.services import MemoryService
from aibridge.domain.models import CandidateRecord, CandidateReviewState, MemoryItem
from aibridge.errors import AIBridgeError

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("", response_model=list[CandidateRecord])
async def list_candidates(
    project_path: Annotated[str, Query(description="Registered project path")],
    memories: Annotated[MemoryService, Depends(get_memories)],
    state: Annotated[CandidateReviewState | None, Query()] = None,
) -> list[CandidateRecord]:
    try:
        records = await asyncio.to_thread(
            memories.list_candidates,
            project_path=Path(project_path),
            state=state,
        )
        return list(records)
    except AIBridgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{candidate_id}/approve", response_model=MemoryItem)
async def approve_candidate(
    candidate_id: str,
    memories: Annotated[MemoryService, Depends(get_memories)],
) -> MemoryItem:
    try:
        return await asyncio.to_thread(memories.approve_candidate, candidate_id)
    except AIBridgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{candidate_id}/reject", response_model=CandidateRecord)
async def reject_candidate(
    candidate_id: str,
    body: RejectCandidateRequest,
    memories: Annotated[MemoryService, Depends(get_memories)],
) -> CandidateRecord:
    try:
        return await asyncio.to_thread(memories.reject_candidate, candidate_id, body.reason)
    except AIBridgeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
