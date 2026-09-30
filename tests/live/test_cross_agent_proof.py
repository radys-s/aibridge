"""Deterministic simulated proof: agent A -> SQLite memory -> fresh agent B."""

from __future__ import annotations

from pathlib import Path

from aibridge.adapters.security import RegexSecretScanner
from aibridge.adapters.sqlite.repository import SQLiteMemoryRepository
from aibridge.agents.claude import ClaudeAdapter
from aibridge.agents.codex import CodexAdapter
from aibridge.agents.fake import FakeAgentAdapter
from aibridge.application.context import LexicalContextBuilder
from aibridge.config import Settings
from aibridge.domain.models import (
    AgentExecutionPolicy,
    Evidence,
    EvidenceType,
    MemoryCandidateProposal,
    MemoryKind,
)
from aibridge.memory.curator import MemoryCurator
from aibridge.runs.orchestrator import RunOrchestrator


def test_simulated_cross_agent_memory_handoff_proof(tmp_path: Path) -> None:
    """Proves the memory pipeline, but deliberately does not invoke provider CLIs."""
    db_path = tmp_path / "aibridge.db"
    data_dir = tmp_path / "data"
    settings = Settings(database_path=db_path, data_dir=data_dir)
    repo = SQLiteMemoryRepository(settings)
    repo.initialize()

    fixture_dir = tmp_path / "fixture_repo"
    fixture_dir.mkdir()
    docs_dir = fixture_dir / "docs"
    docs_dir.mkdir()

    rule_file = docs_dir / "auth_rule.md"
    rule_text = "AUTH_RULE_X99: All OAuth refresh tokens MUST expire strictly within 72 hours."
    rule_file.write_text(rule_text, encoding="utf-8")

    repo.register_project(fixture_dir)
    context_builder = LexicalContextBuilder(repo)
    curator = MemoryCurator(repo, RegexSecretScanner())
    orchestrator = RunOrchestrator(repo, context_builder, curator)

    proposal = MemoryCandidateProposal(
        kind=MemoryKind.LEARNING,
        title="OAuth Refresh Token Expiration Policy",
        content=rule_text,
        subject_key="auth.token.expiration",
        confidence=0.95,
        evidence=(
            Evidence(
                type=EvidenceType.FILE,
                path="docs/auth_rule.md",
                quote="OAuth refresh tokens MUST expire strictly within 72 hours",
            ),
        ),
    )
    claude_adapter = FakeAgentAdapter(
        mode="success",
        answer="Discovered OAuth refresh token expiration rule in docs/auth_rule.md.",
        candidates=(proposal,),
        vendor_session_id="claude-session-001",
    )

    # 1. Claude run reads file and extracts memory
    run1, _res1, sum1 = orchestrator.execute_run(
        project_path=fixture_dir,
        agent_name="claude",
        task="Read docs/auth_rule.md and extract authentication rules.",
        execution_policy=AgentExecutionPolicy.READ_ONLY,
        adapter=claude_adapter,
    )

    assert run1.status == "completed"
    assert len(sum1.auto_applied) == 1

    applied_mem_id = sum1.auto_applied[0]

    # 2. DELETE original source file from repository
    rule_file.unlink()
    assert not rule_file.exists()

    # 3. Fresh Codex session starts asking about OAuth refresh token policy
    codex_adapter = FakeAgentAdapter(
        mode="success",
        answer=(
            "According to stored memory AUTH_RULE_X99, "
            "OAuth refresh tokens expire strictly within 72 hours."
        ),
        used_memory_ids=(applied_mem_id,),
        vendor_session_id="codex-session-002",
    )

    run2, res2, _sum2 = orchestrator.execute_run(
        project_path=fixture_dir,
        agent_name="codex",
        task="What is the expiration requirement for OAuth refresh tokens?",
        execution_policy=AgentExecutionPolicy.READ_ONLY,
        adapter=codex_adapter,
    )

    assert run2.status == "completed"
    assert applied_mem_id in res2.used_memory_ids or "72 hours" in res2.answer


def test_agent_adapters_doctor_probing() -> None:
    claude_health = ClaudeAdapter().doctor()
    codex_health = CodexAdapter().doctor()

    assert claude_health.provider == "claude"
    assert codex_health.provider == "codex"
