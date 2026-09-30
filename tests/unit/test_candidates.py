"""Unit tests for evidence verification, secret scanning, and candidate curation."""

from __future__ import annotations

from pathlib import Path

import pytest

from aibridge.adapters.security import RegexSecretScanner
from aibridge.adapters.sqlite.repository import SQLiteMemoryRepository
from aibridge.config import Settings
from aibridge.domain.models import (
    CandidateReviewState,
    Evidence,
    EvidenceType,
    MemoryCandidateProposal,
    MemoryKind,
    MemoryScope,
)
from aibridge.memory.curator import MemoryCurator
from aibridge.memory.evidence import EvidenceVerifier


@pytest.fixture
def temp_repo(tmp_path: Path) -> tuple[SQLiteMemoryRepository, Path, str, str]:
    db_path = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    settings = Settings(database_path=db_path, data_dir=data_dir)
    repo = SQLiteMemoryRepository(settings)
    repo.initialize()

    proj_dir = tmp_path / "sample_proj"
    proj_dir.mkdir()
    (proj_dir / "docs").mkdir()
    (proj_dir / "docs" / "auth.md").write_text("JWT refresh tokens are rotated after use.")

    proj = repo.register_project(proj_dir)
    space_id, _ = repo.ensure_identity()
    return repo, proj_dir, proj.id, space_id.id


def test_evidence_verifier_valid_file(tmp_path: Path) -> None:
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    (proj_dir / "docs").mkdir()
    (proj_dir / "docs" / "auth.md").write_text("JWT refresh tokens are rotated after use.")

    verifier = EvidenceVerifier()
    evidence = [
        Evidence(
            type=EvidenceType.FILE,
            path="docs/auth.md",
            quote="JWT refresh tokens are rotated",
        )
    ]
    valid, risk_codes = verifier.verify(evidence, proj_dir, "task prompt")
    assert valid is True
    assert len(risk_codes) == 0


def test_evidence_verifier_path_traversal(tmp_path: Path) -> None:
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()

    verifier = EvidenceVerifier()
    evidence = [
        Evidence(
            type=EvidenceType.FILE,
            path="../../outside.txt",
        )
    ]
    valid, risk_codes = verifier.verify(evidence, proj_dir, "task prompt")
    assert valid is False
    assert "file_evidence_path_traversal" in risk_codes


def test_evidence_verifier_checks_line_ranges(tmp_path: Path) -> None:
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    evidence_file = proj_dir / "rules.txt"
    evidence_file.write_text("first line\nrotation is 72 hours\nlast line", encoding="utf-8")
    verifier = EvidenceVerifier()

    valid, codes = verifier.verify(
        [
            Evidence(
                type=EvidenceType.FILE,
                path="rules.txt",
                line_start=2,
                line_end=2,
                quote="72 hours",
            )
        ],
        proj_dir,
        "task",
    )
    assert valid is True
    assert codes == ()

    valid, codes = verifier.verify(
        [
            Evidence(
                type=EvidenceType.FILE,
                path="rules.txt",
                line_start=3,
                line_end=4,
                quote="72 hours",
            )
        ],
        proj_dir,
        "task",
    )
    assert valid is False
    assert "file_evidence_invalid_line_range" in codes


def test_candidate_curator_secret_rejection(
    temp_repo: tuple[SQLiteMemoryRepository, Path, str, str],
) -> None:
    repo, proj_dir, proj_id, space_id = temp_repo
    curator = MemoryCurator(repo, RegexSecretScanner())

    proposal = MemoryCandidateProposal(
        kind=MemoryKind.LEARNING,
        title="Secret API Key",
        content="The secret key is sk_live_1234567890abcdef12345678",
        confidence=0.95,
    )

    summary = curator.process_proposals(
        space_id=space_id,
        project_id=proj_id,
        project_path=proj_dir,
        task_prompt="task",
        proposals=[proposal],
    )

    assert len(summary.blocked_secret) == 1
    cands = repo.list_candidates(project_id=proj_id, state=CandidateReviewState.BLOCKED_SECRET)
    assert len(cands) == 1
    assert cands[0].proposal.content == "[REDACTED_SECRET]"


def test_candidate_curator_auto_apply_policy(
    temp_repo: tuple[SQLiteMemoryRepository, Path, str, str],
) -> None:
    repo, proj_dir, proj_id, space_id = temp_repo
    curator = MemoryCurator(repo, RegexSecretScanner())

    proposal = MemoryCandidateProposal(
        kind=MemoryKind.LEARNING,
        scope=MemoryScope.PROJECT,
        title="JWT Rotation Policy",
        content="Refresh token rotace je zapnutá.",
        confidence=0.95,
        evidence=(
            Evidence(
                type=EvidenceType.FILE,
                path="docs/auth.md",
                quote="JWT refresh tokens are rotated",
            ),
        ),
    )

    summary = curator.process_proposals(
        space_id=space_id,
        project_id=proj_id,
        project_path=proj_dir,
        task_prompt="task",
        proposals=[proposal],
    )

    assert len(summary.auto_applied) == 1
    memories = repo.list_memories(project_id=proj_id).items
    assert any(m.title == "JWT Rotation Policy" for m in memories)
