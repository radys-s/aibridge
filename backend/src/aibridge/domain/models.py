"""Provider- and persistence-independent, versioned domain contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ShortId = Annotated[str, StringConstraints(min_length=1, max_length=100)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
MemoryTitle = Annotated[str, StringConstraints(min_length=1, max_length=300)]
MemoryContent = Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
SubjectKey = Annotated[str, StringConstraints(min_length=1, max_length=300)]


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class FrozenModel(BaseModel):
    """Deeply composable immutable value object used at application boundaries."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class MemoryKind(StrEnum):
    ARCHITECTURE = "architecture"
    DECISION = "decision"
    LEARNING = "learning"
    STATE = "state"
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"


class MemoryScope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    UNCERTAIN = "uncertain"
    SUPERSEDED = "superseded"


class EdgeKind(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    DEPENDS_ON = "depends_on"
    RELATES_TO = "relates_to"
    DERIVED_FROM = "derived_from"
    IMPLEMENTS = "implements"
    AFFECTS = "affects"


class CandidateRelation(StrEnum):
    NEW = "new"
    SUPPORTS = "supports"
    UPDATES = "updates"
    CONTRADICTS = "contradicts"


class CandidateReviewState(StrEnum):
    PENDING = "pending"
    AUTO_APPLIED = "auto_applied"
    APPROVED = "approved"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    BLOCKED_SECRET = "blocked_secret"


class EvidenceType(StrEnum):
    FILE = "file"
    USER = "user"
    RUN = "run"


class AgentExecutionPolicy(StrEnum):
    READ_ONLY = "read-only"
    NATIVE = "native"


class Space(FrozenModel):
    id: ShortId
    name: Name
    created_at: datetime


class Device(FrozenModel):
    id: ShortId
    name: Name
    platform: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    created_at: datetime


class Project(FrozenModel):
    id: ShortId
    space_id: ShortId
    name: Name
    created_at: datetime
    updated_at: datetime


class ProjectMount(FrozenModel):
    id: ShortId
    project_id: ShortId
    device_id: ShortId
    path: str
    created_at: datetime
    updated_at: datetime


class Evidence(FrozenModel):
    type: EvidenceType
    path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    quote: str | None = None


class Provenance(FrozenModel):
    id: ShortId
    memory_item_id: ShortId
    memory_revision_id: ShortId
    source_type: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    source_agent: str | None = None
    source_run_id: str | None = None
    source_commit: str | None = None
    evidence_path: str | None = None
    evidence_excerpt: str | None = None
    evidence_hash: str | None = None
    created_at: datetime


class MemoryItem(FrozenModel):
    id: ShortId
    space_id: ShortId
    project_id: ShortId | None
    scope: MemoryScope
    kind: MemoryKind
    status: MemoryStatus
    subject_key: SubjectKey | None
    title: MemoryTitle
    content: MemoryContent
    importance: int = Field(ge=0, le=100)
    volatility: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    pinned: bool
    revision_id: ShortId
    revision_number: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    superseded_by_id: str | None = None
    provenance: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def validate_scope(self) -> MemoryItem:
        if self.scope is MemoryScope.PROJECT and self.project_id is None:
            raise ValueError("project-scoped memory requires project_id")
        if self.scope is MemoryScope.GLOBAL and self.project_id is not None:
            raise ValueError("global memory cannot have project_id")
        return self


class MemorySearchHit(FrozenModel):
    item: MemoryItem
    score: float
    reason: Literal["pinned", "fts5"]


class MemoryPage(FrozenModel):
    items: tuple[MemoryItem, ...]
    next_cursor: str | None
    limit: int = Field(ge=1, le=100)


class ContextItem(FrozenModel):
    memory_id: ShortId
    kind: MemoryKind
    title: MemoryTitle
    content: MemoryContent
    score: float
    reason: Literal["pinned", "fts5"]


class OmittedContextItems(FrozenModel):
    count: int = Field(ge=0)
    memory_ids: tuple[ShortId, ...]

    @model_validator(mode="after")
    def validate_count(self) -> OmittedContextItems:
        if self.count != len(self.memory_ids):
            raise ValueError("omitted count must equal the number of memory IDs")
        return self


class ContextPacket(FrozenModel):
    schema_name: Literal["aibridge.context"] = "aibridge.context"
    version: Literal[1] = 1
    project_id: ShortId
    task_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    memory_revision: str
    max_chars: int = Field(ge=512, le=8_000)
    security_notice: str
    objective: str
    rendered: str
    items: tuple[ContextItem, ...]
    omitted: OmittedContextItems

    @model_validator(mode="after")
    def validate_budget(self) -> ContextPacket:
        if len(self.rendered) > self.max_chars:
            raise ValueError("rendered context exceeds max_chars")
        return self


class MemoryCandidateProposal(FrozenModel):
    kind: MemoryKind
    scope: MemoryScope = MemoryScope.PROJECT
    subject_key: SubjectKey | None = None
    title: MemoryTitle
    content: MemoryContent
    importance: int = Field(default=50, ge=0, le=100)
    confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    relation: CandidateRelation = CandidateRelation.NEW
    related_memory_id: ShortId | None = None
    evidence: tuple[Evidence, ...] = ()


class CandidateRecord(FrozenModel):
    id: ShortId
    space_id: ShortId
    project_id: ShortId | None
    proposed_by_run_id: ShortId | None
    state: CandidateReviewState
    relation: CandidateRelation
    related_memory_id: ShortId | None
    applied_memory_id: ShortId | None = None
    proposal: MemoryCandidateProposal
    risk_codes: tuple[str, ...] = ()
    resolution_reason: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class AgentRunRequest(FrozenModel):
    run_id: ShortId
    space_id: ShortId
    project_id: ShortId
    project_path: Path
    task: str
    context: ContextPacket
    execution_policy: AgentExecutionPolicy = AgentExecutionPolicy.READ_ONLY
    resume_vendor_session_id: str | None = None


class AgentRunResult(FrozenModel):
    outcome: Literal["completed", "failed", "cancelled"]
    answer: str
    used_memory_ids: tuple[ShortId, ...] = ()
    memory_candidates: tuple[MemoryCandidateProposal, ...] = ()
    vendor_session_id: str | None = None
    error_message: str | None = None


class RunRecord(FrozenModel):
    id: ShortId
    space_id: ShortId
    project_id: ShortId
    agent: str
    vendor_session_id: str | None = None
    task_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    status: Literal["running", "completed", "failed", "cancelled"]
    execution_policy: AgentExecutionPolicy
    exit_code: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class IngestSummary(FrozenModel):
    auto_applied: tuple[ShortId, ...] = ()
    pending: tuple[ShortId, ...] = ()
    duplicates: tuple[ShortId, ...] = ()
    blocked_secret: tuple[ShortId, ...] = ()
    rejected: tuple[ShortId, ...] = ()


class EventOrigin(FrozenModel):
    device_id: ShortId
    source: Literal["local"] = "local"


class SpaceCreatedPayload(FrozenModel):
    kind: Literal["space.created"] = "space.created"
    version: Literal[1] = 1
    space: Space


class DeviceCreatedPayload(FrozenModel):
    kind: Literal["device.created"] = "device.created"
    version: Literal[1] = 1
    device: Device


class MountRecord(FrozenModel):
    id: ShortId
    project_id: ShortId
    device_id: ShortId
    path_key: str
    path_display: str
    created_at: datetime
    updated_at: datetime


class ProjectRegisteredPayload(FrozenModel):
    kind: Literal["project.registered"] = "project.registered"
    version: Literal[1] = 1
    project: Project
    mount: MountRecord

    @model_validator(mode="after")
    def validate_mount(self) -> ProjectRegisteredPayload:
        if self.mount.project_id != self.project.id:
            raise ValueError("mount project_id must match project payload")
        return self


class MemoryItemRecord(FrozenModel):
    id: ShortId
    space_id: ShortId
    project_id: ShortId | None
    scope: MemoryScope
    kind: MemoryKind
    status: MemoryStatus
    subject_key: SubjectKey | None
    importance: int = Field(ge=0, le=100)
    volatility: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    pinned: bool
    current_revision_id: ShortId
    valid_from: datetime | None
    valid_to: datetime | None
    superseded_by_id: str | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_scope(self) -> MemoryItemRecord:
        if (self.scope is MemoryScope.PROJECT) != (self.project_id is not None):
            raise ValueError("memory scope and project_id do not agree")
        return self


class MemoryRevisionRecord(FrozenModel):
    revision_id: ShortId
    memory_item_id: ShortId
    revision_number: int = Field(ge=1)
    title: MemoryTitle
    content: MemoryContent
    created_at: datetime


class MemoryCreatedPayload(FrozenModel):
    kind: Literal["memory.created"] = "memory.created"
    version: Literal[1] = 1
    item: MemoryItemRecord
    revision: MemoryRevisionRecord
    provenance: tuple[Provenance, ...]

    @model_validator(mode="after")
    def validate_references(self) -> MemoryCreatedPayload:
        if self.revision.memory_item_id != self.item.id:
            raise ValueError("revision memory_item_id must match item")
        if self.item.current_revision_id != self.revision.revision_id:
            raise ValueError("current revision must match revision payload")
        if any(
            entry.memory_item_id != self.item.id
            or entry.memory_revision_id != self.revision.revision_id
            for entry in self.provenance
        ):
            raise ValueError("provenance references must match memory payload")
        return self


class CandidateCreatedPayload(FrozenModel):
    kind: Literal["candidate.created"] = "candidate.created"
    version: Literal[1] = 1
    candidate: CandidateRecord


class CandidateResolvedPayload(FrozenModel):
    kind: Literal["candidate.resolved"] = "candidate.resolved"
    version: Literal[1] = 1
    candidate: CandidateRecord


class RunRecordedPayload(FrozenModel):
    kind: Literal["run.recorded"] = "run.recorded"
    version: Literal[1] = 1
    run: RunRecord


class RunContextItemPayload(FrozenModel):
    """One injected memory reference, retained for event replay and audit."""

    memory_id: ShortId
    position: int = Field(ge=0)
    reason: Annotated[str, StringConstraints(min_length=1, max_length=50)]


class RunContextRecordedPayload(FrozenModel):
    kind: Literal["run.context.recorded"] = "run.context.recorded"
    version: Literal[1] = 1
    run_id: ShortId
    items: tuple[RunContextItemPayload, ...]


EventPayload = Annotated[
    SpaceCreatedPayload
    | DeviceCreatedPayload
    | ProjectRegisteredPayload
    | MemoryCreatedPayload
    | CandidateCreatedPayload
    | CandidateResolvedPayload
    | RunRecordedPayload
    | RunContextRecordedPayload,
    Field(discriminator="kind"),
]


class ChangeEvent(FrozenModel):
    schema_name: Literal["aibridge.change-event"] = "aibridge.change-event"
    envelope_version: Literal[1] = 1
    id: ShortId
    space_id: ShortId
    device_id: ShortId
    project_id: ShortId | None
    aggregate_type: Literal["space", "device", "project", "memory_item", "memory_candidate", "run"]
    aggregate_id: ShortId
    event_type: Literal[
        "space.created",
        "device.created",
        "project.registered",
        "memory.created",
        "candidate.created",
        "candidate.resolved",
        "run.recorded",
        "run.context.recorded",
    ]
    payload: EventPayload
    origin: EventOrigin
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_envelope(self) -> ChangeEvent:
        if self.event_type != self.payload.kind:
            raise ValueError("event_type must match payload discriminator")
        if self.device_id != self.origin.device_id:
            raise ValueError("event device_id must match origin device_id")
        if isinstance(self.payload, SpaceCreatedPayload):
            valid = (
                self.aggregate_type == "space"
                and self.aggregate_id == self.payload.space.id
                and self.space_id == self.payload.space.id
                and self.project_id is None
            )
        elif isinstance(self.payload, DeviceCreatedPayload):
            valid = (
                self.aggregate_type == "device"
                and self.aggregate_id == self.payload.device.id
                and self.device_id == self.payload.device.id
                and self.project_id is None
            )
        elif isinstance(self.payload, ProjectRegisteredPayload):
            valid = (
                self.aggregate_type == "project"
                and self.aggregate_id == self.payload.project.id
                and self.project_id == self.payload.project.id
                and self.space_id == self.payload.project.space_id
                and self.device_id == self.payload.mount.device_id
            )
        elif isinstance(self.payload, MemoryCreatedPayload):
            valid = (
                self.aggregate_type == "memory_item"
                and self.aggregate_id == self.payload.item.id
                and self.project_id == self.payload.item.project_id
                and self.space_id == self.payload.item.space_id
            )
        elif isinstance(self.payload, (CandidateCreatedPayload, CandidateResolvedPayload)):
            valid = (
                self.aggregate_type == "memory_candidate"
                and self.aggregate_id == self.payload.candidate.id
                and self.project_id == self.payload.candidate.project_id
                and self.space_id == self.payload.candidate.space_id
            )
        elif isinstance(self.payload, RunRecordedPayload):
            valid = (
                self.aggregate_type == "run"
                and self.aggregate_id == self.payload.run.id
                and self.project_id == self.payload.run.project_id
                and self.space_id == self.payload.run.space_id
            )
        elif isinstance(self.payload, RunContextRecordedPayload):
            valid = self.aggregate_type == "run" and self.aggregate_id == self.payload.run_id
        else:  # pragma: no cover - protects future discriminated-union additions.
            valid = False
        if not valid:
            raise ValueError("event envelope does not match typed payload")
        return self


class RemoteIngestResult(FrozenModel):
    accepted: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    quarantined: int = Field(ge=0)


class HealthReport(FrozenModel):
    database_path: str
    sqlite_version: str
    schema_version: int
    fts5_available: bool
    journal_mode: str
    foreign_keys: bool
    trusted_schema: bool
    integrity: str


class AgentHealth(FrozenModel):
    available: bool
    provider: str
    detail: str | None = None


class CommandRequest(FrozenModel):
    workspace: Path
    argv: tuple[str, ...]


class CommandResult(FrozenModel):
    exit_code: int
    stdout: str
    stderr: str


class SecretScanResult(FrozenModel):
    safe: bool
    finding_codes: tuple[str, ...]


class ExtractionRequest(FrozenModel):
    run: AgentRunResult


class MemoryCandidateData(FrozenModel):
    kind: MemoryKind
    title: MemoryTitle
    content: MemoryContent


class SemanticMatch(FrozenModel):
    memory_id: ShortId
    score: float


class GitStatusResult(FrozenModel):
    branch: str | None
    dirty: bool
    changed_paths: tuple[str, ...]


class UsageRemaining(FrozenModel):
    provider: str
    amount: float | None
    unit: str | None
    estimated: bool


class EncryptedEvent(FrozenModel):
    event_id: ShortId
    ciphertext: bytes


class SyncPushResult(FrozenModel):
    cursor: str


class SyncPullResult(FrozenModel):
    events: tuple[EncryptedEvent, ...]
    cursor: str
