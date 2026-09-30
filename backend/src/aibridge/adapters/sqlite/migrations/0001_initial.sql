CREATE TABLE app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE space (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE device (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    platform TEXT NOT NULL CHECK (length(platform) BETWEEN 1 AND 100),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE project (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL REFERENCES space(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (id, space_id)
) STRICT;

CREATE TABLE project_mount (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES device(id) ON DELETE CASCADE,
    path_key TEXT NOT NULL,
    path_display TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (device_id, path_key)
) STRICT;

CREATE TABLE memory_item (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL REFERENCES space(id) ON DELETE RESTRICT,
    project_id TEXT,
    scope TEXT NOT NULL CHECK (scope IN ('global', 'project')),
    kind TEXT NOT NULL CHECK (
        kind IN ('architecture', 'decision', 'learning', 'state', 'preference', 'constraint')
    ),
    status TEXT NOT NULL CHECK (status IN ('active', 'uncertain', 'superseded')),
    subject_key TEXT,
    importance INTEGER NOT NULL CHECK (importance BETWEEN 0 AND 100),
    volatility INTEGER NOT NULL CHECK (volatility BETWEEN 0 AND 100),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    pinned INTEGER NOT NULL CHECK (pinned IN (0, 1)),
    current_revision_id TEXT REFERENCES memory_revision(revision_id) DEFERRABLE INITIALLY DEFERRED,
    valid_from TEXT,
    valid_to TEXT,
    superseded_by_id TEXT REFERENCES memory_item(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id, space_id) REFERENCES project(id, space_id) ON DELETE CASCADE,
    CHECK (
        (scope = 'project' AND project_id IS NOT NULL)
        OR (scope = 'global' AND project_id IS NULL)
    )
) STRICT;

CREATE TABLE memory_revision (
    revision_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id TEXT NOT NULL UNIQUE,
    memory_item_id TEXT NOT NULL REFERENCES memory_item(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 20000),
    created_at TEXT NOT NULL,
    UNIQUE (memory_item_id, revision_number)
) STRICT;

CREATE TABLE memory_provenance (
    id TEXT PRIMARY KEY,
    memory_item_id TEXT NOT NULL REFERENCES memory_item(id) ON DELETE CASCADE,
    memory_revision_id TEXT NOT NULL REFERENCES memory_revision(revision_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK (length(source_type) BETWEEN 1 AND 50),
    source_agent TEXT,
    source_run_id TEXT,
    source_commit TEXT,
    evidence_path TEXT,
    evidence_excerpt TEXT,
    evidence_hash TEXT,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE memory_edge (
    id TEXT PRIMARY KEY,
    source_item_id TEXT NOT NULL REFERENCES memory_item(id) ON DELETE CASCADE,
    target_item_id TEXT NOT NULL REFERENCES memory_item(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'supports', 'contradicts', 'supersedes', 'depends_on',
            'relates_to', 'derived_from', 'implements', 'affects'
        )
    ),
    created_at TEXT NOT NULL,
    UNIQUE (source_item_id, target_item_id, kind)
) STRICT;

CREATE TABLE memory_candidate (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL REFERENCES space(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES project(id) ON DELETE CASCADE,
    proposed_by_run_id TEXT,
    state TEXT NOT NULL CHECK (
        state IN ('pending', 'auto_applied', 'approved', 'rejected', 'duplicate', 'blocked_secret')
    ),
    relation TEXT NOT NULL CHECK (relation IN ('new', 'supports', 'updates', 'contradicts')),
    related_memory_id TEXT REFERENCES memory_item(id) ON DELETE SET NULL,
    payload_json TEXT NOT NULL,
    risk_codes_json TEXT NOT NULL DEFAULT '[]',
    resolution_reason TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
) STRICT;

CREATE TABLE change_event (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    schema_name TEXT NOT NULL CHECK (schema_name = 'aibridge.change-event'),
    envelope_version INTEGER NOT NULL CHECK (envelope_version = 1),
    space_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    project_id TEXT,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    origin_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL
) STRICT;

CREATE TABLE event_quarantine (
    quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,
    payload_sha256 TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    detail TEXT NOT NULL,
    received_at TEXT NOT NULL
) STRICT;

CREATE TABLE sync_outbox (
    event_id TEXT PRIMARY KEY REFERENCES change_event(event_id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'sent')),
    created_at TEXT NOT NULL,
    sent_at TEXT
) STRICT;

CREATE VIRTUAL TABLE memory_fts USING fts5(
    title,
    content,
    content='memory_revision',
    content_rowid='revision_seq',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE INDEX idx_project_space ON project(space_id);
CREATE INDEX idx_mount_project ON project_mount(project_id);
CREATE INDEX idx_memory_project_status ON memory_item(project_id, status);
CREATE INDEX idx_memory_space_scope_status ON memory_item(space_id, scope, status);
CREATE INDEX idx_memory_subject ON memory_item(project_id, subject_key) WHERE subject_key IS NOT NULL;
CREATE INDEX idx_revision_item ON memory_revision(memory_item_id, revision_number);
CREATE INDEX idx_provenance_item ON memory_provenance(memory_item_id);
CREATE INDEX idx_event_project_sequence ON change_event(project_id, sequence);
CREATE INDEX idx_outbox_state ON sync_outbox(state, created_at);

CREATE TRIGGER memory_revision_no_update
BEFORE UPDATE ON memory_revision
BEGIN
    SELECT RAISE(ABORT, 'memory_revision is append-only');
END;

CREATE TRIGGER memory_revision_no_delete
BEFORE DELETE ON memory_revision
BEGIN
    SELECT RAISE(ABORT, 'memory_revision is append-only');
END;

CREATE TRIGGER change_event_no_update
BEFORE UPDATE ON change_event
BEGIN
    SELECT RAISE(ABORT, 'change_event is append-only');
END;

CREATE TRIGGER change_event_no_delete
BEFORE DELETE ON change_event
BEGIN
    SELECT RAISE(ABORT, 'change_event is append-only');
END;
