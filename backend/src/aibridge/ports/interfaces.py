"""Hexagonal architecture ports with typed, versionable boundaries."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from aibridge.domain.models import (
    AgentExecutionPolicy,
    AgentHealth,
    AgentRunRequest,
    AgentRunResult,
    CandidateRecord,
    CandidateReviewState,
    ChangeEvent,
    CommandRequest,
    CommandResult,
    ContextPacket,
    Device,
    EncryptedEvent,
    ExtractionRequest,
    GitStatusResult,
    HealthReport,
    MemoryCandidateData,
    MemoryCandidateProposal,
    MemoryItem,
    MemoryKind,
    MemoryPage,
    MemoryScope,
    MemorySearchHit,
    MemoryStatus,
    Project,
    RemoteIngestResult,
    RunRecord,
    SecretScanResult,
    SemanticMatch,
    Space,
    SyncPullResult,
    SyncPushResult,
    UsageRemaining,
)


class MemoryRepository(Protocol):
    def initialize(self) -> None: ...

    def health(self) -> HealthReport: ...

    def ensure_identity(self) -> tuple[Space, Device]: ...

    def register_project(self, path: Path, name: str | None = None) -> Project: ...

    def find_project_by_path(self, path: Path) -> Project | None: ...

    def add_memory(
        self,
        *,
        space_id: str,
        project_id: str | None,
        scope: MemoryScope,
        kind: MemoryKind,
        title: str,
        content: str,
        subject_key: str | None,
        importance: int,
        volatility: int,
        confidence: float,
        pinned: bool,
    ) -> MemoryItem: ...

    def list_memories(
        self,
        *,
        project_id: str,
        status: MemoryStatus | None = None,
        include_global: bool = True,
        limit: int = 25,
        cursor: str | None = None,
    ) -> MemoryPage: ...

    def get_memory(self, memory_id: str) -> MemoryItem | None: ...

    def search_memories(
        self, *, project_id: str, task: str, limit: int = 12
    ) -> Sequence[MemorySearchHit]: ...

    def memory_revision_token(self, project_id: str) -> str: ...

    def record_run_start(
        self,
        *,
        space_id: str,
        project_id: str,
        agent: str,
        execution_policy: AgentExecutionPolicy,
        task_hash: str,
        vendor_session_id: str | None = None,
    ) -> RunRecord: ...

    def record_run_context(self, *, run_id: str, items: Sequence[tuple[str, int, str]]) -> None: ...

    def finalize_run(
        self,
        *,
        run_id: str,
        status: str,
        exit_code: int | None = None,
        vendor_session_id: str | None = None,
    ) -> RunRecord: ...

    def get_run(self, run_id: str) -> RunRecord | None: ...

    def list_runs(self, *, project_id: str, limit: int = 25) -> Sequence[RunRecord]: ...

    def save_candidate(
        self,
        *,
        space_id: str,
        project_id: str,
        proposal: MemoryCandidateProposal,
        run_id: str | None = None,
        state: CandidateReviewState = CandidateReviewState.PENDING,
        risk_codes: Sequence[str] = (),
        reason: str | None = None,
    ) -> CandidateRecord: ...

    def list_candidates(
        self, *, project_id: str, state: CandidateReviewState | None = None
    ) -> Sequence[CandidateRecord]: ...

    def get_candidate(self, candidate_id: str) -> CandidateRecord | None: ...

    def resolve_candidate(
        self,
        *,
        candidate_id: str,
        state: CandidateReviewState,
        reason: str | None = None,
        applied_memory_id: str | None = None,
    ) -> CandidateRecord: ...

    def list_events(self) -> Sequence[ChangeEvent]: ...

    def rebuild_projection(self, events: Iterable[ChangeEvent]) -> None: ...

    def ingest_remote(self, events: Iterable[object]) -> RemoteIngestResult: ...


class ContextRetriever(Protocol):
    def build(self, *, project: Project, task: str, max_chars: int = 8_000) -> ContextPacket: ...


class AgentAdapter(Protocol):
    def doctor(self) -> AgentHealth: ...

    def run(self, request: AgentRunRequest) -> AgentRunResult: ...


class MemoryExtractor(Protocol):
    def extract(self, request: ExtractionRequest) -> Sequence[MemoryCandidateData]: ...


class SemanticIndex(Protocol):
    def index(self, memory_id: str, text: str) -> None: ...

    def query(self, text: str, *, limit: int) -> Sequence[SemanticMatch]: ...


class ExecutionBackend(Protocol):
    def create_workspace(self, project: Project, task_id: str) -> Path: ...

    def run_command(self, request: CommandRequest) -> CommandResult: ...


class GitProvider(Protocol):
    def status(self, workspace: Path) -> GitStatusResult: ...

    def diff(self, workspace: Path) -> str: ...


class UsageProvider(Protocol):
    def remaining(self, provider: str) -> UsageRemaining: ...


class SecretScanner(Protocol):
    def scan(self, text: str) -> SecretScanResult: ...


class SyncTransport(Protocol):
    def push(self, encrypted_events: Sequence[EncryptedEvent]) -> SyncPushResult: ...

    def pull(self, cursor: str | None) -> SyncPullResult: ...


class KeyProvider(Protocol):
    def get_space_key(self, space_id: str) -> bytes: ...
