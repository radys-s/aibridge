"""RunOrchestrator coordinating context building, agent run, and memory ingestion."""

from __future__ import annotations

import hashlib
from pathlib import Path

from aibridge.agents.base import AgentAdapter
from aibridge.agents.claude import ClaudeAdapter
from aibridge.agents.codex import CodexAdapter
from aibridge.domain.models import (
    AgentExecutionPolicy,
    AgentRunRequest,
    AgentRunResult,
    IngestSummary,
    RunRecord,
)
from aibridge.errors import AgentAdapterError, DomainValidationError
from aibridge.memory.curator import MemoryCurator
from aibridge.ports.interfaces import ContextRetriever, MemoryRepository


class RunOrchestrator:
    """Manages the full lifecycle of an AI Bridge agent run."""

    def __init__(
        self,
        repository: MemoryRepository,
        context_retriever: ContextRetriever,
        curator: MemoryCurator,
    ) -> None:
        self._repository = repository
        self._context_retriever = context_retriever
        self._curator = curator

    def execute_run(
        self,
        *,
        project_path: Path,
        agent_name: str,
        task: str,
        execution_policy: AgentExecutionPolicy = AgentExecutionPolicy.READ_ONLY,
        resume_vendor_session_id: str | None = None,
        max_chars: int = 8_000,
        adapter: AgentAdapter | None = None,
    ) -> tuple[RunRecord, AgentRunResult, IngestSummary]:
        project = self._repository.find_project_by_path(project_path)
        if project is None:
            raise DomainValidationError(f"Project path '{project_path}' is not registered")

        task_hash = hashlib.sha256(task.strip().encode()).hexdigest()
        context_packet = self._context_retriever.build(
            project=project, task=task, max_chars=max_chars
        )

        run_record = self._repository.record_run_start(
            space_id=project.space_id,
            project_id=project.id,
            agent=agent_name,
            execution_policy=execution_policy,
            task_hash=task_hash,
            vendor_session_id=resume_vendor_session_id,
        )

        context_items = [
            (item.memory_id, idx, item.reason) for idx, item in enumerate(context_packet.items)
        ]
        self._repository.record_run_context(run_id=run_record.id, items=context_items)

        if adapter is None:
            if agent_name == "claude":
                adapter = ClaudeAdapter()
            elif agent_name == "codex":
                adapter = CodexAdapter()
            else:
                raise DomainValidationError(f"Unsupported agent provider '{agent_name}'")

        request = AgentRunRequest(
            run_id=run_record.id,
            space_id=project.space_id,
            project_id=project.id,
            project_path=project_path,
            task=task,
            context=context_packet,
            execution_policy=execution_policy,
            resume_vendor_session_id=resume_vendor_session_id,
        )

        try:
            agent_result = adapter.run(request)
        except Exception as error:
            self._repository.finalize_run(run_id=run_record.id, status="failed", exit_code=1)
            raise AgentAdapterError(f"Agent execution failed: {error}") from error

        # Ensure used_memory_ids is strictly a subset of injected context items
        injected_ids = {item.memory_id for item in context_packet.items}
        valid_used_ids = tuple(
            mem_id for mem_id in agent_result.used_memory_ids if mem_id in injected_ids
        )
        verified_agent_result = agent_result.model_copy(update={"used_memory_ids": valid_used_ids})

        if verified_agent_result.outcome == "completed":
            summary = self._curator.process_proposals(
                space_id=project.space_id,
                project_id=project.id,
                project_path=project_path,
                task_prompt=task,
                proposals=verified_agent_result.memory_candidates,
                run_id=run_record.id,
            )
            exit_code = 0
        else:
            # Failed/cancelled provider output is not evidence for durable memory.
            summary = IngestSummary()
            exit_code = 1 if verified_agent_result.outcome == "failed" else 130

        final_run = self._repository.finalize_run(
            run_id=run_record.id,
            status=verified_agent_result.outcome,
            exit_code=exit_code,
            vendor_session_id=verified_agent_result.vendor_session_id,
        )

        return final_run, verified_agent_result, summary
