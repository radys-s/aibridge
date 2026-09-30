"""Candidate ingestion, evidence verification, secret scanning, and auto-write curation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from aibridge.domain.models import (
    CandidateRecord,
    CandidateReviewState,
    IngestSummary,
    MemoryCandidateProposal,
    MemoryItem,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
)
from aibridge.memory.evidence import EvidenceVerifier
from aibridge.ports.interfaces import MemoryRepository, SecretScanner


class MemoryCurator:
    """Ingests candidate proposals through security, evidence, deduplication, and policy gates."""

    def __init__(
        self,
        repository: MemoryRepository,
        secret_scanner: SecretScanner,
        evidence_verifier: EvidenceVerifier | None = None,
    ) -> None:
        self._repository = repository
        self._scanner = secret_scanner
        self._verifier = evidence_verifier or EvidenceVerifier()

    def process_proposals(
        self,
        *,
        space_id: str,
        project_id: str,
        project_path: Path,
        task_prompt: str,
        proposals: Sequence[MemoryCandidateProposal],
        run_id: str | None = None,
    ) -> IngestSummary:
        auto_applied: list[str] = []
        pending: list[str] = []
        duplicates: list[str] = []
        blocked_secret: list[str] = []
        rejected: list[str] = []

        existing_memories = self._repository.list_memories(
            project_id=project_id, status=MemoryStatus.ACTIVE, limit=100
        ).items

        for proposal in proposals:
            # 1. Secret scan
            combined_text = f"{proposal.title}\n{proposal.content}"
            scan_result = self._scanner.scan(combined_text)
            if not scan_result.safe:
                cand = self._repository.save_candidate(
                    space_id=space_id,
                    project_id=project_id,
                    proposal=proposal.model_copy(
                        update={"content": "[REDACTED_SECRET]", "title": "[REDACTED_SECRET]"}
                    ),
                    run_id=run_id,
                    state=CandidateReviewState.BLOCKED_SECRET,
                    risk_codes=scan_result.finding_codes,
                    reason="Candidate contained detected secret values",
                )
                blocked_secret.append(cand.id)
                continue

            # 2. Evidence verification
            evidence_valid, risk_codes = self._verifier.verify(
                proposal.evidence, project_path, task_prompt
            )

            # 3. Deduplication check
            is_exact_dup = any(
                m.title == proposal.title and m.content == proposal.content
                for m in existing_memories
            )
            if is_exact_dup:
                cand = self._repository.save_candidate(
                    space_id=space_id,
                    project_id=project_id,
                    proposal=proposal,
                    run_id=run_id,
                    state=CandidateReviewState.DUPLICATE,
                    risk_codes=risk_codes,
                    reason="Exact memory title and content already exists",
                )
                duplicates.append(cand.id)
                continue

            # 4. Check subject key conflicts
            has_conflict = False
            related_id = proposal.related_memory_id
            if proposal.subject_key:
                matches = [m for m in existing_memories if m.subject_key == proposal.subject_key]
                if matches:
                    has_conflict = True
                    if not related_id:
                        related_id = matches[0].id

            updated_proposal = proposal.model_copy(update={"related_memory_id": related_id})

            # 5. Conservative auto-write policy evaluation
            can_auto_apply = (
                evidence_valid
                and proposal.confidence >= 0.90
                and proposal.scope is MemoryScope.PROJECT
                and proposal.kind in (MemoryKind.LEARNING, MemoryKind.STATE)
                and not has_conflict
            )

            if can_auto_apply:
                # Add memory item to repository
                mem = self._repository.add_memory(
                    space_id=space_id,
                    project_id=project_id,
                    scope=proposal.scope,
                    kind=proposal.kind,
                    title=proposal.title,
                    content=proposal.content,
                    subject_key=proposal.subject_key,
                    importance=proposal.importance,
                    volatility=50,
                    confidence=proposal.confidence,
                    pinned=False,
                )
                cand = self._repository.save_candidate(
                    space_id=space_id,
                    project_id=project_id,
                    proposal=updated_proposal,
                    run_id=run_id,
                    state=CandidateReviewState.AUTO_APPLIED,
                    risk_codes=risk_codes,
                    reason="Auto-applied under conservative policy",
                )
                self._repository.resolve_candidate(
                    candidate_id=cand.id,
                    state=CandidateReviewState.AUTO_APPLIED,
                    applied_memory_id=mem.id,
                )
                auto_applied.append(cand.id)
            else:
                cand = self._repository.save_candidate(
                    space_id=space_id,
                    project_id=project_id,
                    proposal=updated_proposal,
                    run_id=run_id,
                    state=CandidateReviewState.PENDING,
                    risk_codes=risk_codes,
                    reason="Requires manual review"
                    if not evidence_valid
                    else "Pending review policy",
                )
                pending.append(cand.id)

        return IngestSummary(
            auto_applied=tuple(auto_applied),
            pending=tuple(pending),
            duplicates=tuple(duplicates),
            blocked_secret=tuple(blocked_secret),
            rejected=tuple(rejected),
        )

    def approve_candidate(self, candidate_id: str) -> MemoryItem:
        cand = self._repository.get_candidate(candidate_id)
        if cand is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        if cand.state != CandidateReviewState.PENDING:
            raise ValueError(f"Candidate {candidate_id} is in state {cand.state}, cannot approve")

        p = cand.proposal
        mem = self._repository.add_memory(
            space_id=cand.space_id,
            project_id=cand.project_id,
            scope=p.scope,
            kind=p.kind,
            title=p.title,
            content=p.content,
            subject_key=p.subject_key,
            importance=p.importance,
            volatility=50,
            confidence=p.confidence,
            pinned=False,
        )
        self._repository.resolve_candidate(
            candidate_id=cand.id,
            state=CandidateReviewState.APPROVED,
            reason="Manually approved by user",
            applied_memory_id=mem.id,
        )
        return mem

    def reject_candidate(self, candidate_id: str, reason: str) -> CandidateRecord:
        cand = self._repository.get_candidate(candidate_id)
        if cand is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        return self._repository.resolve_candidate(
            candidate_id=cand.id,
            state=CandidateReviewState.REJECTED,
            reason=reason,
        )
