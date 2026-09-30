"""Pydantic request/response schemas for the /v1 REST API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from aibridge.domain.models import (
    AgentExecutionPolicy,
    MemoryKind,
    MemoryScope,
)


class RegisterProjectRequest(BaseModel):
    path: str = Field(description="Absolute path to an existing local directory")
    name: str | None = Field(default=None, description="Optional display name")


class AddMemoryRequest(BaseModel):
    project_path: str = Field(description="Registered project path")
    kind: MemoryKind
    title: str
    content: str
    scope: MemoryScope = MemoryScope.PROJECT
    subject_key: str | None = None
    importance: int = Field(default=50, ge=0, le=100)
    volatility: int = Field(default=50, ge=0, le=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    pinned: bool = False


class StartRunRequest(BaseModel):
    project_path: str = Field(description="Registered project path")
    agent: str = Field(description="'claude' or 'codex'")
    task: str = Field(description="Task prompt for the agent")
    execution_policy: AgentExecutionPolicy = AgentExecutionPolicy.READ_ONLY
    resume_vendor_session_id: str | None = None


class RejectCandidateRequest(BaseModel):
    reason: str = Field(min_length=1)


class ErrorResponse(BaseModel):
    code: str
    detail: str
