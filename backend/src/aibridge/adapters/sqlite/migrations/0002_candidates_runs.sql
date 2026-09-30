CREATE TABLE run (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL REFERENCES space(id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    agent TEXT NOT NULL CHECK (length(agent) BETWEEN 1 AND 50),
    vendor_session_id TEXT,
    task_hash TEXT NOT NULL CHECK (length(task_hash) = 64),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    execution_policy TEXT NOT NULL CHECK (execution_policy IN ('read-only', 'native')),
    exit_code INTEGER,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (project_id, space_id) REFERENCES project(id, space_id) ON DELETE CASCADE
) STRICT;

CREATE TABLE run_context_item (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    memory_id TEXT NOT NULL REFERENCES memory_item(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 50),
    created_at TEXT NOT NULL,
    UNIQUE (run_id, position)
) STRICT;

CREATE INDEX idx_run_project ON run(project_id, created_at);
CREATE INDEX idx_candidate_project_state ON memory_candidate(project_id, state);
CREATE INDEX idx_run_context_run ON run_context_item(run_id, position);
