"""Transactional SQLite memory repository and validated event projection."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from aibridge.config import Settings
from aibridge.domain.models import (
    AgentExecutionPolicy,
    CandidateCreatedPayload,
    CandidateRecord,
    CandidateRelation,
    CandidateResolvedPayload,
    CandidateReviewState,
    ChangeEvent,
    Device,
    DeviceCreatedPayload,
    EventOrigin,
    HealthReport,
    MemoryCandidateProposal,
    MemoryCreatedPayload,
    MemoryItem,
    MemoryItemRecord,
    MemoryKind,
    MemoryPage,
    MemoryRevisionRecord,
    MemoryScope,
    MemorySearchHit,
    MemoryStatus,
    MountRecord,
    Project,
    ProjectRegisteredPayload,
    Provenance,
    RemoteIngestResult,
    RunContextItemPayload,
    RunContextRecordedPayload,
    RunRecord,
    RunRecordedPayload,
    Space,
    SpaceCreatedPayload,
    utc_now,
)
from aibridge.errors import DomainValidationError, MigrationError, RepositoryError

TOKEN_PATTERN: Final = re.compile(r"[^\W_]{2,}(?:[._/-][^\W_]+)*", re.UNICODE)
MIGRATION_PATTERN: Final = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
MAX_PAGE_SIZE: Final = 100


def _new_id() -> str:
    return str(uuid4())


def _timestamp() -> str:
    return utc_now().isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _path_parts(path: Path) -> tuple[str, str]:
    resolved = str(path.expanduser().resolve(strict=False))
    key = os.path.normcase(resolved)
    if os.name == "nt":
        key = key.casefold()
    return key, resolved


def build_fts_query(text: str, *, max_terms: int = 16) -> str | None:
    """Convert untrusted task text into a quoted FTS expression."""
    terms: list[str] = []
    seen: set[str] = set()
    for match in TOKEN_PATTERN.finditer(text):
        term = match.group(0).casefold()
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= max_terms:
            break
    if not terms:
        return None
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def _migration_statements(sql: str) -> Iterator[str]:
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise MigrationError("Migration contains an incomplete SQL statement")


class SQLiteMemoryRepository:
    """SQLite adapter maintaining validated events and projections atomically."""

    def __init__(
        self,
        settings: Settings,
        *,
        event_id_factory: Callable[[], str] = _new_id,
    ) -> None:
        self._settings = settings
        self._event_id_factory = event_id_factory

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._settings.data_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self._settings.database_path,
            timeout=self._settings.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {self._settings.busy_timeout_ms:d}")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA trusted_schema = OFF")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self, connection: sqlite3.Connection) -> Iterator[None]:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()

    def initialize(self) -> None:
        """Serialize first initialization and verify the complete migration history."""
        try:
            with self._connect() as connection, self._transaction(connection):
                self._probe_fts5(connection)
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migration (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        checksum_sha256 TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    ) STRICT
                    """
                )
                migrations = self._load_migrations()
                applied_rows = connection.execute(
                    """
                    SELECT version, name, checksum_sha256
                    FROM schema_migration ORDER BY version
                    """
                ).fetchall()
                applied_versions = [int(row["version"]) for row in applied_rows]
                if applied_versions != list(range(1, len(applied_versions) + 1)):
                    raise MigrationError(
                        "Applied migration sequence is not contiguous from version 1"
                    )

                by_version = {
                    version: (name, checksum, sql) for version, name, checksum, sql in migrations
                }
                for row in applied_rows:
                    version = int(row["version"])
                    expected = by_version.get(version)
                    if expected is None:
                        raise MigrationError(
                            f"Applied migration {version} is missing from the package"
                        )
                    if (str(row["name"]), str(row["checksum_sha256"])) != expected[:2]:
                        raise MigrationError(
                            f"Applied migration {version} name or SHA-256 checksum has changed"
                        )

                applied = set(applied_versions)
                for version, name, checksum, sql in migrations:
                    if version in applied:
                        continue
                    for statement in _migration_statements(sql):
                        connection.execute(statement)
                    connection.execute(
                        """
                        INSERT INTO schema_migration(version, name, checksum_sha256, applied_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (version, name, checksum, _timestamp()),
                    )
        except MigrationError:
            raise
        except (sqlite3.Error, OSError) as error:
            raise MigrationError(f"Database initialization failed: {error}") from error

    @staticmethod
    def _load_migrations() -> list[tuple[int, str, str, str]]:
        migration_dir = Path(__file__).with_name("migrations")
        migrations: list[tuple[int, str, str, str]] = []
        for path in migration_dir.glob("*.sql"):
            match = MIGRATION_PATTERN.fullmatch(path.name)
            if match is None:
                continue
            sql = path.read_text(encoding="utf-8")
            migrations.append(
                (int(match.group(1)), path.name, hashlib.sha256(sql.encode()).hexdigest(), sql)
            )
        migrations.sort(key=lambda entry: entry[0])
        versions = [entry[0] for entry in migrations]
        if versions != list(range(1, len(versions) + 1)):
            raise MigrationError("Packaged migration sequence must be contiguous from version 1")
        return migrations

    @staticmethod
    def _probe_fts5(connection: sqlite3.Connection) -> None:
        try:
            connection.execute("CREATE VIRTUAL TABLE temp.aibridge_fts5_probe USING fts5(value)")
            connection.execute("DROP TABLE temp.aibridge_fts5_probe")
        except sqlite3.Error as error:
            raise MigrationError("This Python SQLite build does not provide FTS5") from error

    def health(self) -> HealthReport:
        try:
            with self._connect() as connection:
                self._probe_fts5(connection)
                schema_row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migration"
                ).fetchone()
                journal = connection.execute("PRAGMA journal_mode").fetchone()
                foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
                trusted_schema = connection.execute("PRAGMA trusted_schema").fetchone()
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                assert schema_row and journal and foreign_keys and trusted_schema and integrity
                connection.execute("INSERT INTO memory_fts(memory_fts) VALUES ('integrity-check')")
                return HealthReport(
                    database_path=str(self._settings.database_path),
                    sqlite_version=sqlite3.sqlite_version,
                    schema_version=int(schema_row["version"]),
                    fts5_available=True,
                    journal_mode=str(journal[0]),
                    foreign_keys=bool(foreign_keys[0]),
                    trusted_schema=bool(trusted_schema[0]),
                    integrity=str(integrity[0]),
                )
        except (sqlite3.Error, OSError) as error:
            raise RepositoryError(f"Database health check failed: {error}") from error

    def ensure_identity(self) -> tuple[Space, Device]:
        try:
            with self._connect() as connection, self._transaction(connection):
                rows = {
                    str(row["key"]): str(row["value"])
                    for row in connection.execute(
                        "SELECT key, value FROM app_meta WHERE key IN (?, ?)",
                        ("default_space_id", "default_device_id"),
                    )
                }
                if "default_space_id" in rows and "default_device_id" in rows:
                    return self._load_identity(connection, rows)

                now = utc_now()
                space = Space(id=_new_id(), name="Personal", created_at=now)
                device = Device(
                    id=_new_id(),
                    name=platform.node() or "Local device",
                    platform=platform.system().lower() or "unknown",
                    created_at=now,
                )
                connection.execute(
                    "INSERT INTO space(id, name, created_at) VALUES (?, ?, ?)",
                    (space.id, space.name, space.created_at.isoformat()),
                )
                connection.execute(
                    "INSERT INTO device(id, name, platform, created_at) VALUES (?, ?, ?, ?)",
                    (device.id, device.name, device.platform, device.created_at.isoformat()),
                )
                connection.executemany(
                    "INSERT INTO app_meta(key, value) VALUES (?, ?)",
                    (("default_space_id", space.id), ("default_device_id", device.id)),
                )
                self._append_event(
                    connection,
                    event=ChangeEvent(
                        id=self._event_id_factory(),
                        space_id=space.id,
                        device_id=device.id,
                        project_id=None,
                        aggregate_type="space",
                        aggregate_id=space.id,
                        event_type="space.created",
                        payload=SpaceCreatedPayload(space=space),
                        origin=EventOrigin(device_id=device.id),
                        occurred_at=now,
                    ),
                    enqueue_outbound=True,
                )
                self._append_event(
                    connection,
                    event=ChangeEvent(
                        id=self._event_id_factory(),
                        space_id=space.id,
                        device_id=device.id,
                        project_id=None,
                        aggregate_type="device",
                        aggregate_id=device.id,
                        event_type="device.created",
                        payload=DeviceCreatedPayload(device=device),
                        origin=EventOrigin(device_id=device.id),
                        occurred_at=now,
                    ),
                    enqueue_outbound=True,
                )
                return space, device
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not initialize local identity: {error}") from error

    @staticmethod
    def _load_identity(
        connection: sqlite3.Connection, values: dict[str, str]
    ) -> tuple[Space, Device]:
        space_row = connection.execute(
            "SELECT id, name, created_at FROM space WHERE id = ?", (values["default_space_id"],)
        ).fetchone()
        device_row = connection.execute(
            "SELECT id, name, platform, created_at FROM device WHERE id = ?",
            (values["default_device_id"],),
        ).fetchone()
        if space_row is None or device_row is None:
            raise RepositoryError("Default identity metadata is inconsistent")
        return Space(**dict(space_row)), Device(**dict(device_row))

    def register_project(self, path: Path, name: str | None = None) -> Project:
        space, device = self.ensure_identity()
        path_key, path_display = _path_parts(path)
        try:
            with self._connect() as connection, self._transaction(connection):
                existing = connection.execute(
                    """
                    SELECT p.* FROM project AS p
                    JOIN project_mount AS pm ON pm.project_id = p.id
                    WHERE pm.device_id = ? AND pm.path_key = ?
                    """,
                    (device.id, path_key),
                ).fetchone()
                if existing is not None:
                    return Project(**dict(existing))

                now = utc_now()
                project = Project(
                    id=_new_id(),
                    space_id=space.id,
                    name=(name or path.resolve(strict=False).name or "Project").strip(),
                    created_at=now,
                    updated_at=now,
                )
                mount = MountRecord(
                    id=_new_id(),
                    project_id=project.id,
                    device_id=device.id,
                    path_key=path_key,
                    path_display=path_display,
                    created_at=now,
                    updated_at=now,
                )
                payload = ProjectRegisteredPayload(project=project, mount=mount)
                self._insert_project_projection(connection, payload)
                self._append_event(
                    connection,
                    event=ChangeEvent(
                        id=self._event_id_factory(),
                        space_id=space.id,
                        device_id=device.id,
                        project_id=project.id,
                        aggregate_type="project",
                        aggregate_id=project.id,
                        event_type="project.registered",
                        payload=payload,
                        origin=EventOrigin(device_id=device.id),
                        occurred_at=now,
                    ),
                    enqueue_outbound=True,
                )
                return project
        except (sqlite3.Error, PydanticValidationError) as error:
            raise RepositoryError(f"Could not register project: {error}") from error

    @staticmethod
    def _insert_project_projection(
        connection: sqlite3.Connection, payload: ProjectRegisteredPayload
    ) -> None:
        connection.execute(
            """
            INSERT INTO project(id, space_id, name, created_at, updated_at)
            VALUES (:id, :space_id, :name, :created_at, :updated_at)
            """,
            payload.project.model_dump(mode="json"),
        )
        connection.execute(
            """
            INSERT INTO project_mount(
                id, project_id, device_id, path_key, path_display, created_at, updated_at
            ) VALUES (
                :id, :project_id, :device_id, :path_key, :path_display, :created_at, :updated_at
            )
            """,
            payload.mount.model_dump(mode="json"),
        )

    def find_project_by_path(self, path: Path) -> Project | None:
        path_key, _ = _path_parts(path)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT p.* FROM project AS p
                    JOIN project_mount AS pm ON pm.project_id = p.id
                    JOIN app_meta AS meta
                      ON meta.key = 'default_device_id' AND meta.value = pm.device_id
                    WHERE pm.path_key = ?
                    """,
                    (path_key,),
                ).fetchone()
                return Project(**dict(row)) if row is not None else None
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not find project: {error}") from error

    def get_project_by_id(self, project_id: str) -> Project | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM project WHERE id = ?", (project_id,)
                ).fetchone()
                return Project(**dict(row)) if row is not None else None
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not get project: {error}") from error

    def list_projects(self) -> Sequence[Project]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM project ORDER BY created_at ASC"
                ).fetchall()
                return [Project(**dict(row)) for row in rows]
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not list projects: {error}") from error

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
    ) -> MemoryItem:
        now = utc_now()
        item_id = _new_id()
        revision_id = _new_id()
        try:
            provenance = Provenance(
                id=_new_id(),
                memory_item_id=item_id,
                memory_revision_id=revision_id,
                source_type="manual",
                source_agent="user",
                created_at=now,
            )
            candidate = MemoryItem(
                id=item_id,
                space_id=space_id,
                project_id=project_id,
                scope=scope,
                kind=kind,
                status=MemoryStatus.ACTIVE,
                subject_key=subject_key.strip() if subject_key else None,
                title=title.strip(),
                content=content.strip(),
                importance=importance,
                volatility=volatility,
                confidence=confidence,
                pinned=pinned,
                revision_id=revision_id,
                revision_number=1,
                created_at=now,
                updated_at=now,
                provenance=(provenance,),
            )
        except PydanticValidationError as error:
            raise DomainValidationError("Memory input failed schema validation") from error
        try:
            with self._connect() as connection, self._transaction(connection):
                if project_id is not None:
                    project = connection.execute(
                        "SELECT 1 FROM project WHERE id = ? AND space_id = ?",
                        (project_id, space_id),
                    ).fetchone()
                    if project is None:
                        raise DomainValidationError(
                            "Project-scoped memory must reference a project in the same space"
                        )
                device_row = connection.execute(
                    "SELECT value FROM app_meta WHERE key = 'default_device_id'"
                ).fetchone()
                if device_row is None:
                    raise RepositoryError("Device identity is not initialized")
                event = self._memory_created_event(candidate, str(device_row["value"]))
                assert isinstance(event.payload, MemoryCreatedPayload)
                self._insert_memory_projection(connection, event.payload)
                self._append_event(connection, event=event, enqueue_outbound=True)
        except (DomainValidationError, RepositoryError):
            raise
        except (sqlite3.Error, PydanticValidationError) as error:
            raise RepositoryError(f"Could not add memory: {error}") from error
        stored = self.get_memory(item_id)
        if stored is None:
            raise RepositoryError("Memory transaction committed without a readable projection")
        return stored

    def _memory_created_event(self, item: MemoryItem, device_id: str) -> ChangeEvent:
        payload = MemoryCreatedPayload(
            item=MemoryItemRecord(
                id=item.id,
                space_id=item.space_id,
                project_id=item.project_id,
                scope=item.scope,
                kind=item.kind,
                status=item.status,
                subject_key=item.subject_key,
                importance=item.importance,
                volatility=item.volatility,
                confidence=item.confidence,
                pinned=item.pinned,
                current_revision_id=item.revision_id,
                valid_from=item.valid_from,
                valid_to=item.valid_to,
                superseded_by_id=item.superseded_by_id,
                created_at=item.created_at,
                updated_at=item.updated_at,
            ),
            revision=MemoryRevisionRecord(
                revision_id=item.revision_id,
                memory_item_id=item.id,
                revision_number=item.revision_number,
                title=item.title,
                content=item.content,
                created_at=item.updated_at,
            ),
            provenance=item.provenance,
        )
        return ChangeEvent(
            id=self._event_id_factory(),
            space_id=item.space_id,
            device_id=device_id,
            project_id=item.project_id,
            aggregate_type="memory_item",
            aggregate_id=item.id,
            event_type="memory.created",
            payload=payload,
            origin=EventOrigin(device_id=device_id),
            occurred_at=item.updated_at,
        )

    @staticmethod
    def _insert_memory_projection(
        connection: sqlite3.Connection, payload: MemoryCreatedPayload
    ) -> None:
        item = payload.item.model_dump(mode="json")
        revision = payload.revision.model_dump(mode="json")
        connection.execute(
            """
            INSERT INTO memory_item(
                id, space_id, project_id, scope, kind, status, subject_key,
                importance, volatility, confidence, pinned, current_revision_id,
                valid_from, valid_to, superseded_by_id, created_at, updated_at
            ) VALUES (
                :id, :space_id, :project_id, :scope, :kind, :status, :subject_key,
                :importance, :volatility, :confidence, :pinned, NULL,
                :valid_from, :valid_to, :superseded_by_id, :created_at, :updated_at
            )
            """,
            item,
        )
        cursor = connection.execute(
            """
            INSERT INTO memory_revision(
                revision_id, memory_item_id, revision_number, title, content, created_at
            ) VALUES (
                :revision_id, :memory_item_id, :revision_number, :title, :content, :created_at
            )
            """,
            revision,
        )
        if cursor.lastrowid is None:
            raise RepositoryError("SQLite did not return the revision rowid")
        connection.execute(
            "UPDATE memory_item SET current_revision_id = ? WHERE id = ?",
            (item["current_revision_id"], item["id"]),
        )
        for entry in payload.provenance:
            connection.execute(
                """
                INSERT INTO memory_provenance(
                    id, memory_item_id, memory_revision_id, source_type, source_agent,
                    source_run_id, source_commit, evidence_path, evidence_excerpt,
                    evidence_hash, created_at
                ) VALUES (
                    :id, :memory_item_id, :memory_revision_id, :source_type, :source_agent,
                    :source_run_id, :source_commit, :evidence_path, :evidence_excerpt,
                    :evidence_hash, :created_at
                )
                """,
                entry.model_dump(mode="json"),
            )
        connection.execute(
            "INSERT INTO memory_fts(rowid, title, content) VALUES (?, ?, ?)",
            (cursor.lastrowid, revision["title"], revision["content"]),
        )

    @staticmethod
    def _encode_cursor(row: sqlite3.Row) -> str:
        payload = [int(row["pinned"]), int(row["importance"]), row["updated_at"], row["id"]]
        return base64.urlsafe_b64encode(_json(payload).encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[int, int, str, str]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
            if (
                not isinstance(value, list)
                or len(value) != 4
                or not isinstance(value[0], int)
                or value[0] not in (0, 1)
                or not isinstance(value[1], int)
                or not isinstance(value[2], str)
                or not isinstance(value[3], str)
            ):
                raise ValueError
            return value[0], value[1], value[2], value[3]
        except (ValueError, UnicodeError, json.JSONDecodeError) as error:
            raise DomainValidationError("Invalid memory page cursor") from error

    def list_memories(
        self,
        *,
        project_id: str,
        status: MemoryStatus | None = None,
        include_global: bool = True,
        limit: int = 25,
        cursor: str | None = None,
    ) -> MemoryPage:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise DomainValidationError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        params: list[object] = [project_id, int(include_global), project_id]
        filters = ""
        if status is not None:
            filters += " AND i.status = ?"
            params.append(status.value)
        if cursor is not None:
            pinned, importance, updated_at, item_id = self._decode_cursor(cursor)
            filters += """
                AND (
                    i.pinned < ?
                    OR (i.pinned = ? AND i.importance < ?)
                    OR (i.pinned = ? AND i.importance = ? AND i.updated_at < ?)
                    OR (
                        i.pinned = ? AND i.importance = ? AND i.updated_at = ? AND i.id > ?
                    )
                )
            """
            params.extend(
                [
                    pinned,
                    pinned,
                    importance,
                    pinned,
                    importance,
                    updated_at,
                    pinned,
                    importance,
                    updated_at,
                    item_id,
                ]
            )
        params.append(limit + 1)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT i.*, r.revision_id, r.revision_number, r.title, r.content
                    FROM project AS p
                    JOIN memory_item AS i ON (
                        i.project_id = ?
                        OR (? = 1 AND i.project_id IS NULL AND i.space_id = p.space_id)
                    )
                    JOIN memory_revision AS r ON r.revision_id = i.current_revision_id
                    WHERE p.id = ? {filters}
                    ORDER BY i.pinned DESC, i.importance DESC, i.updated_at DESC, i.id
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
                has_more = len(rows) > limit
                page_rows = rows[:limit]
                items = self._memories_from_rows(connection, page_rows)
                next_cursor = self._encode_cursor(page_rows[-1]) if has_more else None
                return MemoryPage(items=items, next_cursor=next_cursor, limit=limit)
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not list memory: {error}") from error

    def get_memory(self, memory_id: str) -> MemoryItem | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT i.*, r.revision_id, r.revision_number, r.title, r.content
                    FROM memory_item AS i
                    JOIN memory_revision AS r ON r.revision_id = i.current_revision_id
                    WHERE i.id = ?
                    """,
                    (memory_id,),
                ).fetchone()
                if row is None:
                    return None
                return self._memories_from_rows(connection, [row])[0]
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not read memory: {error}") from error

    @staticmethod
    def _memories_from_rows(
        connection: sqlite3.Connection, rows: Sequence[sqlite3.Row]
    ) -> tuple[MemoryItem, ...]:
        if not rows:
            return ()
        revision_ids = [str(row["revision_id"]) for row in rows]
        placeholders = ",".join("?" for _ in revision_ids)
        provenance_rows = connection.execute(
            f"""
            SELECT * FROM memory_provenance
            WHERE memory_revision_id IN ({placeholders})
            ORDER BY created_at, id
            """,
            revision_ids,
        ).fetchall()
        provenance_by_revision: dict[str, list[Provenance]] = {}
        for entry in provenance_rows:
            provenance_by_revision.setdefault(str(entry["memory_revision_id"]), []).append(
                Provenance(**dict(entry))
            )
        return tuple(
            MemoryItem(
                id=row["id"],
                space_id=row["space_id"],
                project_id=row["project_id"],
                scope=MemoryScope(row["scope"]),
                kind=MemoryKind(row["kind"]),
                status=MemoryStatus(row["status"]),
                subject_key=row["subject_key"],
                title=row["title"],
                content=row["content"],
                importance=row["importance"],
                volatility=row["volatility"],
                confidence=row["confidence"],
                pinned=bool(row["pinned"]),
                revision_id=row["revision_id"],
                revision_number=row["revision_number"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                superseded_by_id=row["superseded_by_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                provenance=tuple(provenance_by_revision.get(str(row["revision_id"]), [])),
            )
            for row in rows
        )

    def search_memories(
        self, *, project_id: str, task: str, limit: int = 12
    ) -> Sequence[MemorySearchHit]:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise DomainValidationError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        try:
            with self._connect() as connection:
                rows_by_id: dict[str, tuple[sqlite3.Row, float, str]] = {}
                pinned_rows = connection.execute(
                    """
                    SELECT i.*, r.revision_id, r.revision_number, r.title, r.content
                    FROM project AS p
                    JOIN memory_item AS i ON (
                        i.project_id = p.id OR (i.project_id IS NULL AND i.space_id = p.space_id)
                    )
                    JOIN memory_revision AS r ON r.revision_id = i.current_revision_id
                    WHERE p.id = ? AND i.status = 'active' AND i.pinned = 1
                    ORDER BY
                        (i.kind = 'constraint') DESC,
                        i.importance DESC,
                        i.updated_at DESC,
                        i.id
                    LIMIT 5
                    """,
                    (project_id,),
                ).fetchall()
                for row in pinned_rows:
                    rows_by_id[str(row["id"])] = (row, 1000 + int(row["importance"]), "pinned")

                fts_query = build_fts_query(task)
                if fts_query and len(rows_by_id) < limit:
                    fts_rows = connection.execute(
                        """
                        SELECT i.*, r.revision_id, r.revision_number, r.title, r.content,
                               bm25(memory_fts, 3.0, 1.0) AS fts_rank
                        FROM memory_fts
                        JOIN memory_revision AS r ON r.revision_seq = memory_fts.rowid
                        JOIN memory_item AS i ON i.current_revision_id = r.revision_id
                        JOIN project AS p ON p.id = ?
                        WHERE memory_fts MATCH ?
                          AND i.status = 'active'
                          AND (
                              i.project_id = p.id
                              OR (i.project_id IS NULL AND i.space_id = p.space_id)
                          )
                        ORDER BY fts_rank, i.importance DESC, i.updated_at DESC, i.id
                        LIMIT ?
                        """,
                        (project_id, fts_query, limit),
                    ).fetchall()
                    for row in fts_rows:
                        item_id = str(row["id"])
                        if item_id not in rows_by_id:
                            score = float(-row["fts_rank"]) + (int(row["importance"]) / 100)
                            rows_by_id[item_id] = (row, score, "fts5")

                ordered = sorted(
                    rows_by_id.values(), key=lambda entry: (-entry[1], str(entry[0]["id"]))
                )[:limit]
                items = self._memories_from_rows(connection, [entry[0] for entry in ordered])
                return tuple(
                    MemorySearchHit(
                        item=item,
                        score=entry[1],
                        reason="pinned" if entry[2] == "pinned" else "fts5",
                    )
                    for item, entry in zip(items, ordered, strict=True)
                )
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not search memory: {error}") from error

    def memory_revision_token(self, project_id: str) -> str:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT i.id, i.current_revision_id, i.status, i.updated_at
                    FROM project AS p
                    JOIN memory_item AS i ON (
                        i.project_id = p.id OR (i.project_id IS NULL AND i.space_id = p.space_id)
                    )
                    WHERE p.id = ? ORDER BY i.id
                    """,
                    (project_id,),
                ).fetchall()
            material = "\n".join(
                f"{row['id']}:{row['current_revision_id']}:{row['status']}:{row['updated_at']}"
                for row in rows
            )
            return hashlib.sha256(material.encode()).hexdigest()[:16]
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not compute memory revision: {error}") from error

    def list_events(self) -> Sequence[ChangeEvent]:
        try:
            with self._connect() as connection:
                rows = connection.execute("SELECT * FROM change_event ORDER BY sequence").fetchall()
            return tuple(self._event_from_row(row) for row in rows)
        except (sqlite3.Error, PydanticValidationError) as error:
            raise RepositoryError(f"Could not read event log: {error}") from error

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> ChangeEvent:
        return ChangeEvent.model_validate(
            {
                "schema_name": row["schema_name"],
                "envelope_version": row["envelope_version"],
                "id": row["event_id"],
                "space_id": row["space_id"],
                "device_id": row["device_id"],
                "project_id": row["project_id"],
                "aggregate_type": row["aggregate_type"],
                "aggregate_id": row["aggregate_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "origin": json.loads(row["origin_json"]),
                "occurred_at": row["occurred_at"],
            }
        )

    def rebuild_projection(self, events: Iterable[ChangeEvent]) -> None:
        """Rebuild an empty local projection from a trusted, typed event history."""
        validated = tuple(ChangeEvent.model_validate(event.model_dump()) for event in events)
        try:
            with self._connect() as connection, self._transaction(connection):
                existing = connection.execute("SELECT 1 FROM change_event LIMIT 1").fetchone()
                if existing is not None:
                    raise DomainValidationError("Projection rebuild requires an empty event log")
                for event in validated:
                    self._apply_projection_event(connection, event)
                    self._append_event(connection, event=event, enqueue_outbound=False)
        except DomainValidationError:
            raise
        except sqlite3.Error as error:
            raise RepositoryError(f"Projection rebuild failed: {error}") from error

    def ingest_remote(self, events: Iterable[object]) -> RemoteIngestResult:
        """Validate remote envelopes, quarantine invalid input, and never echo inbound events."""
        accepted = duplicates = quarantined = 0
        try:
            with self._connect() as connection, self._transaction(connection):
                for raw in events:
                    try:
                        candidate = (
                            raw.model_dump(mode="json") if isinstance(raw, ChangeEvent) else raw
                        )
                        event = ChangeEvent.model_validate(candidate)
                    except PydanticValidationError:
                        self._quarantine(connection, raw, "invalid_envelope")
                        quarantined += 1
                        continue
                    duplicate = connection.execute(
                        "SELECT 1 FROM change_event WHERE event_id = ?", (event.id,)
                    ).fetchone()
                    if duplicate is not None:
                        duplicates += 1
                        continue
                    connection.execute("SAVEPOINT remote_event")
                    try:
                        self._apply_projection_event(connection, event)
                        self._append_event(connection, event=event, enqueue_outbound=False)
                        connection.execute("RELEASE remote_event")
                        accepted += 1
                    except sqlite3.Error:
                        connection.execute("ROLLBACK TO remote_event")
                        connection.execute("RELEASE remote_event")
                        self._quarantine(connection, raw, "projection_rejected")
                        quarantined += 1
            return RemoteIngestResult(
                accepted=accepted, duplicates=duplicates, quarantined=quarantined
            )
        except sqlite3.Error as error:
            raise RepositoryError(f"Remote ingest failed: {error}") from error

    @staticmethod
    def _quarantine(connection: sqlite3.Connection, raw: object, reason: str) -> None:
        try:
            if isinstance(raw, ChangeEvent):
                serializable: object = raw.model_dump(mode="json")
                event_id: str | None = raw.id
            else:
                serializable = raw
                event_id = (
                    raw.get("id")
                    if isinstance(raw, dict) and isinstance(raw.get("id"), str)
                    else None
                )
            material = _json(serializable)
        except (TypeError, ValueError):
            material = repr(type(raw))
            event_id = None
        connection.execute(
            """
            INSERT INTO event_quarantine(
                event_id, payload_sha256, reason_code, detail, received_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_id,
                hashlib.sha256(material.encode()).hexdigest(),
                reason,
                "Raw payload intentionally not persisted",
                _timestamp(),
            ),
        )

    def _apply_projection_event(self, connection: sqlite3.Connection, event: ChangeEvent) -> None:
        payload = event.payload
        if isinstance(payload, SpaceCreatedPayload):
            connection.execute(
                "INSERT INTO space(id, name, created_at) VALUES (:id, :name, :created_at)",
                payload.space.model_dump(mode="json"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('default_space_id', ?)",
                (payload.space.id,),
            )
        elif isinstance(payload, DeviceCreatedPayload):
            connection.execute(
                """
                INSERT INTO device(id, name, platform, created_at)
                VALUES (:id, :name, :platform, :created_at)
                """,
                payload.device.model_dump(mode="json"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('default_device_id', ?)",
                (payload.device.id,),
            )
        elif isinstance(payload, ProjectRegisteredPayload):
            self._insert_project_projection(connection, payload)
        elif isinstance(payload, MemoryCreatedPayload):
            project_id = payload.item.project_id
            if project_id is not None:
                valid_project = connection.execute(
                    "SELECT 1 FROM project WHERE id = ? AND space_id = ?",
                    (project_id, payload.item.space_id),
                ).fetchone()
                if valid_project is None:
                    raise sqlite3.IntegrityError("memory project and space do not match")
            self._insert_memory_projection(connection, payload)
        elif isinstance(payload, CandidateCreatedPayload):
            cand = payload.candidate
            connection.execute(
                """
                INSERT INTO memory_candidate(
                    id, space_id, project_id, proposed_by_run_id, state, relation,
                    related_memory_id, payload_json, risk_codes_json, resolution_reason,
                    created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cand.id,
                    cand.space_id,
                    cand.project_id,
                    cand.proposed_by_run_id,
                    cand.state,
                    cand.relation,
                    cand.related_memory_id,
                    _json(cand.proposal.model_dump(mode="json")),
                    _json(list(cand.risk_codes)),
                    cand.resolution_reason,
                    cand.created_at.isoformat(),
                    cand.resolved_at.isoformat() if cand.resolved_at else None,
                ),
            )
        elif isinstance(payload, CandidateResolvedPayload):
            cand = payload.candidate
            connection.execute(
                """
                UPDATE memory_candidate
                SET state = ?, resolution_reason = ?, resolved_at = ?
                WHERE id = ?
                """,
                (
                    cand.state,
                    cand.resolution_reason,
                    cand.resolved_at.isoformat() if cand.resolved_at else None,
                    cand.id,
                ),
            )
        elif isinstance(payload, RunRecordedPayload):
            r = payload.run
            connection.execute(
                """
                INSERT INTO run(
                    id, space_id, project_id, agent, vendor_session_id, task_hash,
                    status, execution_policy, exit_code, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    vendor_session_id = excluded.vendor_session_id,
                    status = excluded.status,
                    exit_code = excluded.exit_code,
                    completed_at = excluded.completed_at
                """,
                (
                    r.id,
                    r.space_id,
                    r.project_id,
                    r.agent,
                    r.vendor_session_id,
                    r.task_hash,
                    r.status,
                    r.execution_policy,
                    r.exit_code,
                    r.created_at.isoformat(),
                    r.completed_at.isoformat() if r.completed_at else None,
                ),
            )
        elif isinstance(payload, RunContextRecordedPayload):
            for item in payload.items:
                connection.execute(
                    """
                    INSERT INTO run_context_item(
                        id, run_id, memory_id, position, reason, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, position) DO UPDATE SET
                        memory_id = excluded.memory_id,
                        reason = excluded.reason
                    """,
                    (
                        _new_id(),
                        payload.run_id,
                        item.memory_id,
                        item.position,
                        item.reason,
                        event.occurred_at.isoformat(),
                    ),
                )

    def record_run_start(
        self,
        *,
        space_id: str,
        project_id: str,
        agent: str,
        execution_policy: AgentExecutionPolicy,
        task_hash: str,
        vendor_session_id: str | None = None,
    ) -> RunRecord:
        now = utc_now()
        run_record = RunRecord(
            id=_new_id(),
            space_id=space_id,
            project_id=project_id,
            agent=agent,
            vendor_session_id=vendor_session_id,
            task_hash=task_hash,
            status="running",
            execution_policy=execution_policy,
            created_at=now,
        )
        try:
            with self._connect() as connection, self._transaction(connection):
                device_row = connection.execute(
                    "SELECT value FROM app_meta WHERE key = 'default_device_id'"
                ).fetchone()
                if device_row is None:
                    raise RepositoryError("Device identity is not initialized")
                device_id = str(device_row["value"])
                event = ChangeEvent(
                    id=self._event_id_factory(),
                    space_id=space_id,
                    device_id=device_id,
                    project_id=project_id,
                    aggregate_type="run",
                    aggregate_id=run_record.id,
                    event_type="run.recorded",
                    payload=RunRecordedPayload(run=run_record),
                    origin=EventOrigin(device_id=device_id),
                    occurred_at=now,
                )
                self._apply_projection_event(connection, event)
                self._append_event(connection, event=event, enqueue_outbound=True)
            return run_record
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not record run start: {error}") from error

    def record_run_context(self, *, run_id: str, items: Sequence[tuple[str, int, str]]) -> None:
        if not items:
            return
        now = utc_now()
        try:
            with self._connect() as connection, self._transaction(connection):
                run = self._get_run_within_connection(connection, run_id)
                if run is None:
                    raise RepositoryError(f"Run {run_id} not found")
                device_row = connection.execute(
                    "SELECT value FROM app_meta WHERE key = 'default_device_id'"
                ).fetchone()
                if device_row is None:
                    raise RepositoryError("Device identity is not initialized")
                device_id = str(device_row["value"])
                context_items = tuple(
                    RunContextItemPayload(memory_id=memory_id, position=position, reason=reason)
                    for memory_id, position, reason in items
                )
                event = ChangeEvent(
                    id=self._event_id_factory(),
                    space_id=run.space_id,
                    device_id=device_id,
                    project_id=run.project_id,
                    aggregate_type="run",
                    aggregate_id=run.id,
                    event_type="run.context.recorded",
                    payload=RunContextRecordedPayload(run_id=run.id, items=context_items),
                    origin=EventOrigin(device_id=device_id),
                    occurred_at=now,
                )
                self._apply_projection_event(connection, event)
                self._append_event(connection, event=event, enqueue_outbound=True)
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not record run context items: {error}") from error

    def finalize_run(
        self,
        *,
        run_id: str,
        status: str,
        exit_code: int | None = None,
        vendor_session_id: str | None = None,
    ) -> RunRecord:
        now = utc_now()
        try:
            with self._connect() as connection, self._transaction(connection):
                existing = self._get_run_within_connection(connection, run_id)
                if existing is None:
                    raise RepositoryError(f"Run {run_id} not found")
                device_row = connection.execute(
                    "SELECT value FROM app_meta WHERE key = 'default_device_id'"
                ).fetchone()
                if device_row is None:
                    raise RepositoryError("Device identity is not initialized")
                device_id = str(device_row["value"])

                updated_run = RunRecord(
                    id=existing.id,
                    space_id=existing.space_id,
                    project_id=existing.project_id,
                    agent=existing.agent,
                    vendor_session_id=vendor_session_id or existing.vendor_session_id,
                    task_hash=existing.task_hash,
                    status=status,  # type: ignore[arg-type]
                    execution_policy=existing.execution_policy,
                    exit_code=exit_code if exit_code is not None else existing.exit_code,
                    created_at=existing.created_at,
                    completed_at=now,
                )
                event = ChangeEvent(
                    id=self._event_id_factory(),
                    space_id=existing.space_id,
                    device_id=device_id,
                    project_id=existing.project_id,
                    aggregate_type="run",
                    aggregate_id=existing.id,
                    event_type="run.recorded",
                    payload=RunRecordedPayload(run=updated_run),
                    origin=EventOrigin(device_id=device_id),
                    occurred_at=now,
                )
                self._apply_projection_event(connection, event)
                self._append_event(connection, event=event, enqueue_outbound=True)
            return updated_run
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not finalize run: {error}") from error

    def get_run(self, run_id: str) -> RunRecord | None:
        try:
            with self._connect() as connection:
                return self._get_run_within_connection(connection, run_id)
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not read run: {error}") from error

    def list_runs(self, *, project_id: str, limit: int = 25) -> Sequence[RunRecord]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM run WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
                return tuple(self._run_from_row(row) for row in rows)
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not list runs: {error}") from error

    @staticmethod
    def _get_run_within_connection(connection: sqlite3.Connection, run_id: str) -> RunRecord | None:
        row = connection.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
        return SQLiteMemoryRepository._run_from_row(row) if row is not None else None

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RunRecord:
        return RunRecord.model_validate(
            {
                "id": row["id"],
                "space_id": row["space_id"],
                "project_id": row["project_id"],
                "agent": row["agent"],
                "vendor_session_id": row["vendor_session_id"],
                "task_hash": row["task_hash"],
                "status": row["status"],
                "execution_policy": row["execution_policy"],
                "exit_code": row["exit_code"],
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
            }
        )

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
    ) -> CandidateRecord:
        now = utc_now()
        cand_id = _new_id()
        record = CandidateRecord(
            id=cand_id,
            space_id=space_id,
            project_id=project_id,
            proposed_by_run_id=run_id,
            state=state,
            relation=proposal.relation,
            related_memory_id=proposal.related_memory_id,
            proposal=proposal,
            risk_codes=tuple(risk_codes),
            resolution_reason=reason,
            created_at=now,
            resolved_at=now if state != CandidateReviewState.PENDING else None,
        )
        try:
            with self._connect() as connection, self._transaction(connection):
                device_row = connection.execute(
                    "SELECT value FROM app_meta WHERE key = 'default_device_id'"
                ).fetchone()
                if device_row is None:
                    raise RepositoryError("Device identity is not initialized")
                device_id = str(device_row["value"])
                event = ChangeEvent(
                    id=self._event_id_factory(),
                    space_id=space_id,
                    device_id=device_id,
                    project_id=project_id,
                    aggregate_type="memory_candidate",
                    aggregate_id=cand_id,
                    event_type="candidate.created",
                    payload=CandidateCreatedPayload(candidate=record),
                    origin=EventOrigin(device_id=device_id),
                    occurred_at=now,
                )
                self._apply_projection_event(connection, event)
                self._append_event(connection, event=event, enqueue_outbound=True)
            return record
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not save memory candidate: {error}") from error

    def list_candidates(
        self, *, project_id: str, state: CandidateReviewState | None = None
    ) -> Sequence[CandidateRecord]:
        try:
            with self._connect() as connection:
                if state is not None:
                    rows = connection.execute(
                        """
                        SELECT * FROM memory_candidate
                        WHERE project_id = ? AND state = ?
                        ORDER BY created_at DESC
                        """,
                        (project_id, state),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT * FROM memory_candidate
                        WHERE project_id = ?
                        ORDER BY created_at DESC
                        """,
                        (project_id,),
                    ).fetchall()
                return tuple(self._candidate_from_row(row) for row in rows)
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not list candidates: {error}") from error

    def get_candidate(self, candidate_id: str) -> CandidateRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM memory_candidate WHERE id = ?", (candidate_id,)
                ).fetchone()
                return self._candidate_from_row(row) if row is not None else None
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not get candidate: {error}") from error

    def resolve_candidate(
        self,
        *,
        candidate_id: str,
        state: CandidateReviewState,
        reason: str | None = None,
        applied_memory_id: str | None = None,
    ) -> CandidateRecord:
        now = utc_now()
        try:
            with self._connect() as connection, self._transaction(connection):
                existing = self.get_candidate(candidate_id)
                if existing is None:
                    raise RepositoryError(f"Candidate {candidate_id} not found")
                device_row = connection.execute(
                    "SELECT value FROM app_meta WHERE key = 'default_device_id'"
                ).fetchone()
                if device_row is None:
                    raise RepositoryError("Device identity is not initialized")
                device_id = str(device_row["value"])

                updated_record = CandidateRecord(
                    id=existing.id,
                    space_id=existing.space_id,
                    project_id=existing.project_id,
                    proposed_by_run_id=existing.proposed_by_run_id,
                    state=state,
                    relation=existing.relation,
                    related_memory_id=existing.related_memory_id,
                    applied_memory_id=applied_memory_id or existing.applied_memory_id,
                    proposal=existing.proposal,
                    risk_codes=existing.risk_codes,
                    resolution_reason=reason or existing.resolution_reason,
                    created_at=existing.created_at,
                    resolved_at=now,
                )
                event = ChangeEvent(
                    id=self._event_id_factory(),
                    space_id=existing.space_id,
                    device_id=device_id,
                    project_id=existing.project_id,
                    aggregate_type="memory_candidate",
                    aggregate_id=existing.id,
                    event_type="candidate.resolved",
                    payload=CandidateResolvedPayload(candidate=updated_record),
                    origin=EventOrigin(device_id=device_id),
                    occurred_at=now,
                )
                self._apply_projection_event(connection, event)
                self._append_event(connection, event=event, enqueue_outbound=True)
            return updated_record
        except sqlite3.Error as error:
            raise RepositoryError(f"Could not resolve candidate: {error}") from error

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> CandidateRecord:
        proposal_dict = json.loads(row["payload_json"])
        risk_codes = json.loads(row["risk_codes_json"])
        return CandidateRecord(
            id=row["id"],
            space_id=row["space_id"],
            project_id=row["project_id"],
            proposed_by_run_id=row["proposed_by_run_id"],
            state=CandidateReviewState(row["state"]),
            relation=CandidateRelation(row["relation"]),
            related_memory_id=row["related_memory_id"],
            proposal=MemoryCandidateProposal.model_validate(proposal_dict),
            risk_codes=tuple(risk_codes),
            resolution_reason=row["resolution_reason"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection, *, event: ChangeEvent, enqueue_outbound: bool
    ) -> None:
        occurred_at = event.occurred_at.isoformat()
        connection.execute(
            """
            INSERT INTO change_event(
                event_id, schema_name, envelope_version, space_id, device_id, project_id,
                aggregate_type, aggregate_id, event_type, payload_json, origin_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.schema_name,
                event.envelope_version,
                event.space_id,
                event.device_id,
                event.project_id,
                event.aggregate_type,
                event.aggregate_id,
                event.event_type,
                _json(event.payload.model_dump(mode="json")),
                _json(event.origin.model_dump(mode="json")),
                occurred_at,
            ),
        )
        if enqueue_outbound:
            connection.execute(
                "INSERT INTO sync_outbox(event_id, state, created_at) VALUES (?, 'pending', ?)",
                (event.id, occurred_at),
            )
