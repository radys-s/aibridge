"""GET /v1/health — storage and agent health check."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from aibridge.api.deps import get_doctor
from aibridge.application.services import DoctorService
from aibridge.domain.models import HealthReport

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthReport)
async def health(doctor: Annotated[DoctorService, Depends(get_doctor)]) -> HealthReport:
    """Return storage health. No live CLI probing — use the CLI for that."""
    return await asyncio.to_thread(doctor.check)
