"""Abstract base and health checks for agent adapters."""

from __future__ import annotations

from typing import Protocol

from aibridge.domain.models import AgentHealth, AgentRunRequest, AgentRunResult


class AgentAdapter(Protocol):
    """Vendor-neutral contract for AI coding agent CLI adapters."""

    def doctor(self) -> AgentHealth:
        """Check availability, version, and auth state of the CLI."""
        ...

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Execute a single agent run with an injected ContextPacket and output schema."""
        ...
