"""Application services shared by the CLI and future local API."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from aibridge.agents.claude import ClaudeAdapter
from aibridge.agents.codex import CodexAdapter
from aibridge.domain.models import (
    AgentExecutionPolicy,
    AgentHealth,
    AgentRunResult,
    CandidateRecord,
    CandidateReviewState,
    ContextPacket,
    HealthReport,
    IngestSummary,
    MemoryItem,
    MemoryKind,
    MemoryPage,
    MemoryScope,
    MemoryStatus,
    Project,
    RunRecord,
)
from aibridge.errors import (
    DomainValidationError,
    MemoryNotFoundError,
    ProjectNotRegisteredError,
    SecretDetectedError,
)
from aibridge.memory.curator import MemoryCurator
from aibridge.memory.exporter import MarkdownExporter
from aibridge.ports.interfaces import ContextRetriever, MemoryRepository, SecretScanner
from aibridge.runs.orchestrator import RunOrchestrator

DEFAULT_CONTEXT_LIMIT: Final = 8_000
MIN_CONTEXT_LIMIT: Final = 512
MAX_CONTEXT_LIMIT: Final = 8_000


class ProjectService:
    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    def register(self, path: Path, name: str | None = None) -> Project:
        if not path.exists() or not path.is_dir():
            raise DomainValidationError(f"Project path must be an existing directory: {path}")
        return self._repository.register_project(path, name)

    def require(self, path: Path) -> Project:
        project = self._repository.find_project_by_path(path)
        if project is None:
            raise ProjectNotRegisteredError(
                f"Project is not registered: {path}. Run 'aibridge project register <path>'."
            )
        return project


class MemoryService:
    def __init__(
        self,
        repository: MemoryRepository,
        projects: ProjectService,
        secret_scanner: SecretScanner,
        curator: MemoryCurator | None = None,
    ) -> None:
        self._repository = repository
        self._projects = projects
        self._secret_scanner = secret_scanner
        self._curator = curator or MemoryCurator(repository, secret_scanner)

    def add(
        self,
        *,
        project_path: Path,
        kind: MemoryKind,
        title: str,
        content: str,
        scope: MemoryScope = MemoryScope.PROJECT,
        subject_key: str | None = None,
        importance: int = 50,
        volatility: int = 50,
        confidence: float = 1.0,
        pinned: bool = False,
    ) -> MemoryItem:
        scan = self._secret_scanner.scan("\n".join(filter(None, (title, content, subject_key))))
        if not scan.safe:
            raise SecretDetectedError(
                "Memory was rejected because it appears to contain secret material "
                f"({', '.join(scan.finding_codes)})."
            )
        project = self._projects.require(project_path)
        project_id = project.id if scope is MemoryScope.PROJECT else None
        return self._repository.add_memory(
            space_id=project.space_id,
            project_id=project_id,
            scope=scope,
            kind=kind,
            title=title,
            content=content,
            subject_key=subject_key,
            importance=importance,
            volatility=volatility,
            confidence=confidence,
            pinned=pinned,
        )

    def list(
        self,
        *,
        project_path: Path,
        status: MemoryStatus | None = None,
        limit: int = 25,
        cursor: str | None = None,
    ) -> MemoryPage:
        project = self._projects.require(project_path)
        return self._repository.list_memories(
            project_id=project.id,
            status=status,
            include_global=True,
            limit=limit,
            cursor=cursor,
        )

    def show(self, memory_id: str) -> MemoryItem:
        item = self._repository.get_memory(memory_id)
        if item is None:
            raise MemoryNotFoundError(f"Memory item not found: {memory_id}")
        return item

    def list_candidates(
        self, *, project_path: Path, state: CandidateReviewState | None = None
    ) -> Sequence[CandidateRecord]:
        project = self._projects.require(project_path)
        return self._repository.list_candidates(project_id=project.id, state=state)

    def approve_candidate(self, candidate_id: str) -> MemoryItem:
        return self._curator.approve_candidate(candidate_id)

    def reject_candidate(self, candidate_id: str, reason: str) -> CandidateRecord:
        return self._curator.reject_candidate(candidate_id, reason)

    def export_markdown(self, project_path: Path, output_path: Path) -> Path:
        exporter = MarkdownExporter(self._repository)
        return exporter.export(project_path, output_path)


class ContextService:
    def __init__(self, projects: ProjectService, retriever: ContextRetriever) -> None:
        self._projects = projects
        self._retriever = retriever

    def build(
        self, *, project_path: Path, task: str, max_chars: int = DEFAULT_CONTEXT_LIMIT
    ) -> ContextPacket:
        if not MIN_CONTEXT_LIMIT <= max_chars <= MAX_CONTEXT_LIMIT:
            raise DomainValidationError(
                f"max_chars must be between {MIN_CONTEXT_LIMIT} and {MAX_CONTEXT_LIMIT}"
            )
        project = self._projects.require(project_path)
        return self._retriever.build(project=project, task=task, max_chars=max_chars)


class RunService:
    def __init__(
        self,
        repository: MemoryRepository,
        projects: ProjectService,
        orchestrator: RunOrchestrator,
    ) -> None:
        self._repository = repository
        self._projects = projects
        self._orchestrator = orchestrator

    def run(
        self,
        *,
        project_path: Path,
        agent: str,
        task: str,
        execution_policy: AgentExecutionPolicy = AgentExecutionPolicy.READ_ONLY,
        resume_vendor_session_id: str | None = None,
    ) -> tuple[RunRecord, AgentRunResult, IngestSummary]:
        self._projects.require(project_path)
        return self._orchestrator.execute_run(
            project_path=project_path,
            agent_name=agent,
            task=task,
            execution_policy=execution_policy,
            resume_vendor_session_id=resume_vendor_session_id,
        )

    def show(self, run_id: str) -> RunRecord:
        record = self._repository.get_run(run_id)
        if record is None:
            raise DomainValidationError(f"Run '{run_id}' not found")
        return record


class DoctorService:
    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    def check(self) -> HealthReport:
        return self._repository.health()

    def check_live(self) -> dict[str, AgentHealth]:
        claude_health = ClaudeAdapter().doctor()
        codex_health = CodexAdapter().doctor()
        return {"claude": claude_health, "codex": codex_health}
