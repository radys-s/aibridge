"""Deterministic FakeAgentAdapter for testing orchestrator and candidate ingestion."""

from __future__ import annotations

from typing import Literal

from aibridge.domain.models import (
    AgentHealth,
    AgentRunRequest,
    AgentRunResult,
    MemoryCandidateProposal,
)
from aibridge.errors import AgentAdapterError


class FakeAgentAdapter:
    """Configurable test adapter simulating success, partial failures, timeouts, and errors."""

    def __init__(
        self,
        *,
        mode: Literal["success", "timeout", "malformed_json", "auth_failure"] = "success",
        answer: str = "Fake agent successfully executed task.",
        used_memory_ids: tuple[str, ...] = (),
        candidates: tuple[MemoryCandidateProposal, ...] = (),
        vendor_session_id: str | None = "fake-session-123",
    ) -> None:
        self.mode = mode
        self.answer = answer
        self.used_memory_ids = used_memory_ids
        self.candidates = candidates
        self.vendor_session_id = vendor_session_id
        self.run_requests: list[AgentRunRequest] = []

    def doctor(self) -> AgentHealth:
        if self.mode == "auth_failure":
            return AgentHealth(
                available=False, provider="fake", detail="Authentication token missing"
            )
        return AgentHealth(available=True, provider="fake", detail="Fake agent operational")

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.run_requests.append(request)

        if self.mode == "timeout":
            raise AgentAdapterError("Fake agent process timed out after 30 seconds")
        elif self.mode == "auth_failure":
            raise AgentAdapterError("Fake agent authentication failed: invalid API key")
        elif self.mode == "malformed_json":
            raise AgentAdapterError("Failed to parse structured JSON from fake agent output")

        return AgentRunResult(
            outcome="completed",
            answer=self.answer,
            used_memory_ids=self.used_memory_ids,
            memory_candidates=self.candidates,
            vendor_session_id=self.vendor_session_id,
        )
