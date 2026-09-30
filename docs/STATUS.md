# Project status

Updated: 2026-09-17

## Current milestone: Phase 2-5 foundations — candidate pipeline and agent adapters

Implemented:

- Python 3.13 `src`-layout package and CLI composition root.
- Domain types, candidate/run models, and provider-neutral ports.
- SQLite migration policy (v2: `run`, `memory_candidate`, `run_context_item`), stable space/device/project identities, event log/outbox, FTS5 projection.
- `EvidenceVerifier` for strict file path traversal prevention, line range checks, and task quote matching.
- `MemoryCurator` for secret scanning, evidence verification, fingerprint deduplication, subject_key conflict detection, and conservative auto-write policy.
- Vendor-neutral `AgentAdapter` interface, `FakeAgentAdapter`, `ClaudeAdapter` (`claude -p`), and `CodexAdapter` (`codex exec`).
- `RunOrchestrator` managing full lifecycle: run recording, context packet injection, agent execution, candidate ingestion, and run finalization.
- One-way Markdown snapshot exporter (`aibridge export --project <path> --output <file>`).
- CLI subcommands: `doctor [--live]`, `project register`, `memory add/list/show`, `candidate list/approve/reject`, `run`, `run-show`, `export`.
- Deterministic simulated handoff proof: agent A discovers info -> AI Bridge SQLite stores memory -> source file deleted -> fresh agent B receives the stored context. This proves the memory pipeline, not installed provider CLIs.
- Phase A control-plane recovery: run finalization preserves injected context, context recording is evented and replayable, failed/cancelled agent results cannot write memory, and agent schemas are packaged with the wheel.
- Local FastAPI read surface: health, projects, memory, candidates, runs and WebSocket endpoints bind through the app factory. `POST /v1/runs` deliberately returns `501 phase_not_ready` until the durable Phase 3 task worker exists; it does not create a background run.
- The local CLI server is fixed to `127.0.0.1`; permissive CORS is not enabled.

Not implemented yet (Post-MVP):

- Durable API task queue, authenticated browser session, cursor/replay WebSocket stream, and web UI / Tauri Desktop application.
- Isolated Git worktree manager & GitHub approval engine.
- Semantic vector index / local embedding reranker.
- E2E encrypted sync relay & mobile companion client.
- Opt-in live Claude-to-Codex acceptance test on a machine with both authenticated CLIs.

## Verified baseline

On 2026-09-17, the validation suite passed:

- `pytest -q`: 48 passed (two third-party TestClient deprecation warnings).
- `ruff check .`: all checks passed.
- `ruff format --check .`: all files formatted.
- `mypy backend/src tests`: no issues found in 51 source files.
- SQLite smoke: schema version 2, FTS5 available, WAL, foreign keys enabled, `trusted_schema` disabled, integrity `ok`.
