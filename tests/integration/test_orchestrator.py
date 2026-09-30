"""Integration tests for RunOrchestrator and FakeAgentAdapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from aibridge.adapters.security import RegexSecretScanner
from aibridge.adapters.sqlite.repository import SQLiteMemoryRepository
from aibridge.agents.fake import FakeAgentAdapter
from aibridge.application.context import LexicalContextBuilder
from aibridge.config import Settings
from aibridge.domain.models import (
    AgentExecutionPolicy,
    AgentHealth,
    AgentRunRequest,
    AgentRunResult,
    IngestSummary,
    MemoryCandidateProposal,
    MemoryKind,
)
from aibridge.errors import AgentAdapterError
from aibridge.memory.curator import MemoryCurator
from aibridge.runs.orchestrator import RunOrchestrator


@pytest.fixture
def orchestrator_setup(tmp_path: Path) -> tuple[SQLiteMemoryRepository, RunOrchestrator, Path, str]:
    db_path = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    settings = Settings(database_path=db_path, data_dir=data_dir)
    repo = SQLiteMemoryRepository(settings)
    repo.initialize()

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    proj = repo.register_project(proj_dir)

    context_builder = LexicalContextBuilder(repo)
    curator = MemoryCurator(repo, RegexSecretScanner())
    orchestration = RunOrchestrator(repo, context_builder, curator)

    return repo, orchestration, proj_dir, proj.id


def test_orchestrator_successful_fake_run(
    orchestrator_setup: tuple[SQLiteMemoryRepository, RunOrchestrator, Path, str],
) -> None:
    repo, orchestrator, proj_dir, proj_id = orchestrator_setup

    candidate = MemoryCandidateProposal(
        kind=MemoryKind.LEARNING,
        title="Fake Learned Fact",
        content="This is a learned fact from fake agent execution.",
        confidence=0.95,
    )
    fake_adapter = FakeAgentAdapter(mode="success", candidates=(candidate,))

    run_rec, result, summary = orchestrator.execute_run(
        project_path=proj_dir,
        agent_name="fake",
        task="Test fake run execution",
        execution_policy=AgentExecutionPolicy.READ_ONLY,
        adapter=fake_adapter,
    )

    assert run_rec.status == "completed"
    assert result.outcome == "completed"
    assert len(summary.auto_applied) == 1

    runs = repo.list_runs(project_id=proj_id)
    assert len(runs) == 1
    assert runs[0].id == run_rec.id


def test_orchestrator_failed_run_does_not_mutate_memory(
    orchestrator_setup: tuple[SQLiteMemoryRepository, RunOrchestrator, Path, str],
) -> None:
    repo, orchestrator, proj_dir, proj_id = orchestrator_setup

    fake_adapter = FakeAgentAdapter(mode="timeout")

    with pytest.raises(AgentAdapterError):
        orchestrator.execute_run(
            project_path=proj_dir,
            agent_name="fake",
            task="Test failing run",
            adapter=fake_adapter,
        )

    memories = repo.list_memories(project_id=proj_id).items
    assert len(memories) == 0

    runs = repo.list_runs(project_id=proj_id)
    assert len(runs) == 1
    assert runs[0].status == "failed"


def test_completed_only_outcomes_are_allowed_to_create_memory(
    orchestrator_setup: tuple[SQLiteMemoryRepository, RunOrchestrator, Path, str],
) -> None:
    repo, orchestrator, proj_dir, proj_id = orchestrator_setup
    candidate = MemoryCandidateProposal(
        kind=MemoryKind.LEARNING,
        title="Must not persist",
        content="A failed run is not evidence.",
        confidence=0.95,
    )

    class FailedResultAdapter:
        def doctor(self) -> AgentHealth:
            return AgentHealth(available=True, provider="fake", detail="available")

        def run(self, _: AgentRunRequest) -> AgentRunResult:
            return AgentRunResult(
                outcome="failed",
                answer="Provider failed.",
                memory_candidates=(candidate,),
            )

    run, _, summary = orchestrator.execute_run(
        project_path=proj_dir,
        agent_name="fake",
        task="Fail without memory writes",
        adapter=FailedResultAdapter(),
    )

    assert run.status == "failed"
    assert run.exit_code == 1
    assert summary == IngestSummary()
    assert repo.list_memories(project_id=proj_id).items == ()
