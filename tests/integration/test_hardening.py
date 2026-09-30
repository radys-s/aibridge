from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from aibridge.adapters.sqlite.repository import SQLiteMemoryRepository
from aibridge.bootstrap import create_application
from aibridge.config import Settings
from aibridge.domain.models import ChangeEvent, MemoryKind, MemoryScope
from aibridge.errors import (
    DomainValidationError,
    MigrationError,
    SecretDetectedError,
)


def _add(
    repository: SQLiteMemoryRepository,
    project_id: str,
    space_id: str,
    index: int = 0,
) -> str:
    return repository.add_memory(
        space_id=space_id,
        project_id=project_id,
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.LEARNING,
        title=f"Learning {index:03d}",
        content=f"Stable pagination fact {index:03d}",
        subject_key=f"fact.{index:03d}",
        importance=index % 101,
        volatility=20,
        confidence=1.0,
        pinned=index % 17 == 0,
    ).id


def test_revision_and_event_tables_are_database_level_append_only(
    repository: SQLiteMemoryRepository, project_path: Path
) -> None:
    project = repository.register_project(project_path)
    memory_id = _add(repository, project.id, project.space_id)
    event_id = repository.list_events()[-1].id

    with repository._connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE memory_revision SET content = 'changed' WHERE memory_item_id = ?",
                (memory_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM memory_revision WHERE memory_item_id = ?", (memory_id,))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE change_event SET event_type = 'x' WHERE event_id = ?", (event_id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM change_event WHERE event_id = ?", (event_id,))


def test_manual_secret_is_rejected_before_any_content_persists(
    tmp_path: Path, project_path: Path
) -> None:
    settings = Settings.for_database(tmp_path / "secret" / "aibridge.db")
    app = create_application(settings)
    app.projects.register(project_path)
    secret = "sk-proj-abcdefghijklmnopqrstuv"
    before_events = len(app.repository.list_events())

    with pytest.raises(SecretDetectedError) as error:
        app.memories.add(
            project_path=project_path,
            kind=MemoryKind.LEARNING,
            title="Leaked credential",
            content=f"API key is {secret}",
        )

    assert error.value.code == "secret_detected"
    assert secret not in str(error.value)
    assert len(app.repository.list_events()) == before_events
    with app.repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_revision").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] == 0
        event_json = "".join(
            str(row[0]) for row in connection.execute("SELECT payload_json FROM change_event")
        )
    assert secret not in event_json


def test_project_memory_cannot_cross_space(
    repository: SQLiteMemoryRepository, project_path: Path
) -> None:
    project = repository.register_project(project_path)
    with repository._connect() as connection:
        connection.execute(
            "INSERT INTO space(id, name, created_at) VALUES ('other-space', 'Other', 'now')"
        )

    with pytest.raises(DomainValidationError, match="same space"):
        _add(repository, project.id, "other-space")

    with repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_item").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                """
                INSERT INTO memory_item(
                    id, space_id, project_id, scope, kind, status, subject_key,
                    importance, volatility, confidence, pinned, current_revision_id,
                    created_at, updated_at
                ) VALUES (
                    'cross-space-memory', 'other-space', ?, 'project', 'learning', 'active', NULL,
                    50, 50, 1.0, 0, NULL, 'now', 'now'
                )
                """,
                (project.id,),
            )


def test_event_envelope_rejects_payload_space_mismatch(
    repository: SQLiteMemoryRepository, project_path: Path
) -> None:
    project = repository.register_project(project_path)
    _add(repository, project.id, project.space_id)
    raw = repository.list_events()[-1].model_dump(mode="json")
    raw["payload"]["item"]["space_id"] = "wrong-space"

    with pytest.raises(PydanticValidationError, match="envelope"):
        ChangeEvent.model_validate(raw)


def test_concurrent_first_initialization_is_serialized(tmp_path: Path) -> None:
    settings = Settings.for_database(tmp_path / "concurrent" / "aibridge.db")

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(lambda _: SQLiteMemoryRepository(settings).initialize(), range(12)))

    repository = SQLiteMemoryRepository(settings)
    assert repository.health().schema_version == 2
    with repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0] == 2


def test_migration_checksum_is_validated_on_startup(tmp_path: Path) -> None:
    settings = Settings.for_database(tmp_path / "checksum" / "aibridge.db")
    repository = SQLiteMemoryRepository(settings)
    repository.initialize()
    with repository._connect() as connection:
        connection.execute(
            "UPDATE schema_migration SET checksum_sha256 = ? WHERE version = 1", ("0" * 64,)
        )

    with pytest.raises(MigrationError, match="checksum"):
        SQLiteMemoryRepository(settings).initialize()


def test_cursor_pagination_is_bounded_stable_and_complete(
    repository: SQLiteMemoryRepository, project_path: Path
) -> None:
    project = repository.register_project(project_path)
    expected = {_add(repository, project.id, project.space_id, index) for index in range(57)}
    seen: list[str] = []
    cursor: str | None = None
    started = time.perf_counter()

    while True:
        page = repository.list_memories(project_id=project.id, limit=13, cursor=cursor)
        assert len(page.items) <= 13
        assert all(len(item.provenance) == 1 for item in page.items)
        seen.extend(item.id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 57
    assert set(seen) == expected
    assert time.perf_counter() - started < 2.0
    with pytest.raises(DomainValidationError, match="between 1 and 100"):
        repository.list_memories(project_id=project.id, limit=101)


def test_remote_ingest_does_not_echo_and_quarantines_without_raw_payload(
    tmp_path: Path, project_path: Path
) -> None:
    source = SQLiteMemoryRepository(Settings.for_database(tmp_path / "source" / "aibridge.db"))
    source.initialize()
    project = source.register_project(project_path)
    memory_id = _add(source, project.id, project.space_id)
    events = [event.model_dump(mode="json") for event in source.list_events()]

    target = SQLiteMemoryRepository(Settings.for_database(tmp_path / "target" / "aibridge.db"))
    target.initialize()
    result = target.ingest_remote(events)
    assert result.accepted == len(events)
    assert target.get_memory(memory_id) is not None
    with target._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0] == 0

    secret = "sk-proj-thismustneverbepersisted1234"
    invalid = {"id": "bad-event", "event_type": "future.event", "payload": {"secret": secret}}
    rejected = target.ingest_remote([invalid])
    assert rejected.quarantined == 1
    with target._connect() as connection:
        row = connection.execute(
            "SELECT event_id, reason_code, detail FROM event_quarantine"
        ).fetchone()
        assert row is not None
        assert row[0] == "bad-event"
        assert row[1] == "invalid_envelope"
        persisted = "|".join(str(value) for value in row)
    assert secret not in persisted
