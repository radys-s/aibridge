"""Candidate review decisions are made once, atomically."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibridge.adapters.security import RegexSecretScanner
from aibridge.adapters.sqlite.repository import SQLiteMemoryRepository
from aibridge.api.app import create_api_app
from aibridge.config import Settings
from aibridge.domain.models import (
    CandidateRecord,
    CandidateReviewState,
    MemoryCandidateProposal,
    MemoryKind,
    MemoryScope,
)
from aibridge.errors import CandidateStateError
from aibridge.memory.curator import MemoryCurator


@pytest.fixture
def pending(repository: SQLiteMemoryRepository, project_path: Path) -> CandidateRecord:
    project = repository.register_project(project_path)
    return repository.save_candidate(
        space_id=project.space_id,
        project_id=project.id,
        proposal=MemoryCandidateProposal(
            kind=MemoryKind.DECISION,
            scope=MemoryScope.PROJECT,
            title="Use WAL",
            content="The database runs in WAL mode.",
        ),
    )


def _memory_count(repository: SQLiteMemoryRepository, candidate: CandidateRecord) -> int:
    assert candidate.project_id is not None
    return len(repository.list_memories(project_id=candidate.project_id, limit=100).items)


def test_approval_based_on_a_stale_read_is_refused(
    repository: SQLiteMemoryRepository,
    pending: CandidateRecord,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    curator = MemoryCurator(repository, RegexSecretScanner())
    curator.approve_candidate(pending.id)
    # A second agent read the candidate before the first approval committed.
    monkeypatch.setattr(repository, "get_candidate", lambda _: pending)

    with pytest.raises(CandidateStateError):
        curator.approve_candidate(pending.id)
    assert _memory_count(repository, pending) == 1


def test_concurrent_approvals_create_one_memory(
    repository: SQLiteMemoryRepository, pending: CandidateRecord
) -> None:
    curator = MemoryCurator(repository, RegexSecretScanner())
    outcomes: list[str] = []
    start = threading.Barrier(4)

    def approve() -> None:
        start.wait()
        try:
            curator.approve_candidate(pending.id)
            outcomes.append("approved")
        except CandidateStateError:
            outcomes.append("refused")

    threads = [threading.Thread(target=approve) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["approved", "refused", "refused", "refused"]
    assert _memory_count(repository, pending) == 1


def test_approved_candidate_cannot_be_rejected(
    repository: SQLiteMemoryRepository, pending: CandidateRecord
) -> None:
    curator = MemoryCurator(repository, RegexSecretScanner())
    memory = curator.approve_candidate(pending.id)

    with pytest.raises(CandidateStateError):
        curator.reject_candidate(pending.id, "changed my mind")
    stored = repository.get_candidate(pending.id)
    assert stored is not None
    assert stored.state is CandidateReviewState.APPROVED
    assert repository.get_memory(memory.id) is not None


def test_global_candidate_is_approved_as_global_memory(
    repository: SQLiteMemoryRepository, project_path: Path
) -> None:
    project = repository.register_project(project_path)
    candidate = repository.save_candidate(
        space_id=project.space_id,
        project_id=project.id,
        proposal=MemoryCandidateProposal(
            kind=MemoryKind.PREFERENCE,
            scope=MemoryScope.GLOBAL,
            title="Prefer uv",
            content="Use uv for Python environments.",
        ),
    )

    memory = MemoryCurator(repository, RegexSecretScanner()).approve_candidate(candidate.id)

    assert memory.scope is MemoryScope.GLOBAL
    assert memory.project_id is None


def test_api_reports_second_review_as_conflict(
    repository: SQLiteMemoryRepository, pending: CandidateRecord, tmp_path: Path
) -> None:
    app = create_api_app(Settings.for_database(tmp_path / "data" / "aibridge.db"))
    with TestClient(app) as client:
        first = client.patch(f"/v1/candidates/{pending.id}/approve")
        second = client.patch(f"/v1/candidates/{pending.id}/reject", json={"reason": "late"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "candidate_not_pending"
