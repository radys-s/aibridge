from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aibridge.adapters.sqlite.repository import SQLiteMemoryRepository
from aibridge.config import Settings
from aibridge.domain.models import AgentExecutionPolicy, MemoryKind, MemoryScope, MemoryStatus
from aibridge.errors import RepositoryError


def _add_learning(
    repository: SQLiteMemoryRepository,
    *,
    space_id: str,
    project_id: str,
    title: str = "JWT rotation",
    content: str = "Refresh tokens rotate after every successful use.",
) -> str:
    item = repository.add_memory(
        space_id=space_id,
        project_id=project_id,
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.LEARNING,
        title=title,
        content=content,
        subject_key="auth.refresh.rotation",
        importance=80,
        volatility=30,
        confidence=1.0,
        pinned=False,
    )
    return item.id


def test_connection_policy_and_schema_health(repository: SQLiteMemoryRepository) -> None:
    report = repository.health()

    assert report.schema_version == 2
    assert report.fts5_available is True
    assert report.journal_mode == "wal"
    assert report.foreign_keys is True
    assert report.trusted_schema is False
    assert report.integrity == "ok"


def test_memory_persists_after_repository_reopen(tmp_path: Path, project_path: Path) -> None:
    settings = Settings.for_database(tmp_path / "persistent" / "aibridge.db")
    first = SQLiteMemoryRepository(settings)
    first.initialize()
    project = first.register_project(project_path, "Persistent project")
    memory_id = _add_learning(first, space_id=project.space_id, project_id=project.id)

    second = SQLiteMemoryRepository(settings)
    second.initialize()
    reopened = second.get_memory(memory_id)

    assert reopened is not None
    assert reopened.content == "Refresh tokens rotate after every successful use."
    assert reopened.provenance[0].source_type == "manual"


def test_repository_connections_enforce_foreign_keys(
    repository: SQLiteMemoryRepository,
) -> None:
    with repository._connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO project(id, space_id, name, created_at, updated_at)
            VALUES ('invalid-project', 'missing-space', 'Invalid', 'now', 'now')
            """
        )


def test_fts_matches_czech_with_and_without_diacritics(
    repository: SQLiteMemoryRepository, project_path: Path
) -> None:
    project = repository.register_project(project_path)
    memory_id = _add_learning(
        repository,
        space_id=project.space_id,
        project_id=project.id,
        title="Bezpečné přihlášení uživatele",
        content="Přihlášení používá rotaci obnovovacích tokenů.",
    )

    without_accents = repository.search_memories(project_id=project.id, task="prihlaseni")
    with_accents = repository.search_memories(project_id=project.id, task="přihlášení")

    assert [hit.item.id for hit in without_accents] == [memory_id]
    assert [hit.item.id for hit in with_accents] == [memory_id]
    assert repository.health().integrity == "ok"


def test_failed_event_insert_rolls_back_projection_and_fts(
    tmp_path: Path, project_path: Path
) -> None:
    event_ids = iter(
        [
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
            "00000000-0000-4000-8000-000000000003",
            "00000000-0000-4000-8000-000000000004",
            "00000000-0000-4000-8000-000000000004",
        ]
    )
    repository = SQLiteMemoryRepository(
        Settings.for_database(tmp_path / "atomic" / "aibridge.db"),
        event_id_factory=lambda: next(event_ids),
    )
    repository.initialize()
    project = repository.register_project(project_path)
    _add_learning(repository, space_id=project.space_id, project_id=project.id)

    with pytest.raises(RepositoryError):
        _add_learning(
            repository,
            space_id=project.space_id,
            project_id=project.id,
            title="Must roll back",
            content="This projection must not survive a duplicate event ID.",
        )

    page = repository.list_memories(project_id=project.id, status=MemoryStatus.ACTIVE)
    assert len(page.items) == 1
    assert page.items[0].title == "JWT rotation"
    assert repository.search_memories(project_id=project.id, task="must roll back") == ()
    assert repository.health().integrity == "ok"


def test_event_log_replays_into_clean_projection(tmp_path: Path, project_path: Path) -> None:
    source = SQLiteMemoryRepository(Settings.for_database(tmp_path / "source" / "aibridge.db"))
    source.initialize()
    project = source.register_project(project_path, "Replay project")
    memory_id = _add_learning(source, space_id=project.space_id, project_id=project.id)
    source_events = source.list_events()

    target = SQLiteMemoryRepository(Settings.for_database(tmp_path / "target" / "aibridge.db"))
    target.initialize()
    target.rebuild_projection(source_events)

    replayed_project = target.find_project_by_path(project_path)
    replayed_memory = target.get_memory(memory_id)
    assert replayed_project == project
    assert replayed_memory == source.get_memory(memory_id)
    assert target.list_events() == source_events
    assert target.memory_revision_token(project.id) == source.memory_revision_token(project.id)
    assert target.health().integrity == "ok"
    with target._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 0


def test_run_finalization_preserves_and_replays_context_items(
    tmp_path: Path, project_path: Path
) -> None:
    source = SQLiteMemoryRepository(Settings.for_database(tmp_path / "source" / "aibridge.db"))
    source.initialize()
    project = source.register_project(project_path)
    memory_id = _add_learning(source, space_id=project.space_id, project_id=project.id)
    run = source.record_run_start(
        space_id=project.space_id,
        project_id=project.id,
        agent="fake",
        execution_policy=AgentExecutionPolicy.READ_ONLY,
        task_hash="a" * 64,
    )
    source.record_run_context(run_id=run.id, items=((memory_id, 0, "fts5"),))
    source.finalize_run(run_id=run.id, status="completed", exit_code=0)

    with source._connect() as connection:
        rows = connection.execute(
            "SELECT memory_id, position, reason FROM run_context_item WHERE run_id = ?", (run.id,)
        ).fetchall()
    assert [(row["memory_id"], row["position"], row["reason"]) for row in rows] == [
        (memory_id, 0, "fts5")
    ]

    target = SQLiteMemoryRepository(Settings.for_database(tmp_path / "target" / "aibridge.db"))
    target.initialize()
    target.rebuild_projection(source.list_events())
    with target._connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM run_context_item WHERE run_id = ?", (run.id,)
        ).fetchone()[0]
    assert count == 1
