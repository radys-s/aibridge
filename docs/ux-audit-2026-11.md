# Developer-experience audit, November 2026

Audited on 2026-11-19 against `master` at `c507ba3` (v0.1.0). The "users" of AI Bridge are
developers and coding agents that call the CLI and the local HTTP API, so the journeys below are
CLI and API journeys. AI Bridge has no web UI yet: `aibridge serve` exposes only the stock FastAPI
Swagger page, which renders fine at 360 px and at desktop width and has no dark mode of its own
([desktop](screenshots/api-docs-desktop.png), [360 px](screenshots/api-docs-360.png)). There is no
Czech UI text to judge; all CLI and API text is English.

Environment: hub2 (Linux), Python 3.13, `uv sync` in a fresh clone (7.6 s), data under a scratch
`AIBRIDGE_DATA_DIR`. Every finding below was reproduced; commands and output are abbreviated.

## Journeys

| # | Journey | Result |
|---|---|---|
| J1 | README quick start in a fresh clone | Works only after translating PowerShell to a POSIX shell; the final `context build` returns **zero** memory items |
| J2 | `--help` for every command | Works; many flags have no help text or bounds |
| J3 | Store and retrieve memory for a sample project | Works; ~0.27 s per command, 0.57 s for `context build` over 250 memories |
| J4 | Candidate review (`candidate approve/reject`) | Unknown id prints a Python traceback (CLI) or `500 Internal Server Error` (API) |
| J5 | HTTP API errors and validation | FastAPI 422s are clear; application errors have no stable `code`; one path returns 500 |
| J6 | Corrupted, truncated, or newer database | Clean `error[migration_error]`, but no path and no next step |
| J7 | Concurrency: two or more agents writing | 3 writers x 25 `memory add`: all 75 stored, integrity ok. Four concurrent approvals of one candidate: **3 memories created** |
| J8 | Export a project with 250 memories | Snapshot silently contains 100 items and says "Active Memory Items: 100" |

## Findings with evidence

1. **Tracebacks and 500s on unknown candidates or unregistered export paths.**
   `aibridge candidate approve nope` and `candidate reject nope --reason x` end in
   `ValueError: Candidate nope not found` with a full traceback, exit 1.
   `aibridge export --project <unregistered>` does the same. Over HTTP,
   `PATCH /v1/candidates/nope/approve` and `/reject` return `500 Internal Server Error` with a
   plain-text body. Cause: `MemoryCurator` and `MarkdownExporter` raise `ValueError` instead of an
   `AIBridgeError`.
2. **Approving a candidate is not atomic.** Four concurrent `candidate approve <id>` calls on one
   pending candidate created three identical memories. `candidate reject` on an already approved
   candidate flips it to `rejected` while its memory stays active. Cause: the pending-state check
   and the write happen in separate transactions, and `reject` has no state check at all.
3. **Export silently truncates at 100 items.** `MarkdownExporter` reads a single
   `list_memories(limit=100)` page. With 250 memories the snapshot has 100 entries and reports 100.
4. **The README quick start does not demonstrate retrieval.** It is PowerShell only (backticks,
   `C:\path`), and its example stores "Refresh token rotation" but asks for
   "Update authentication". Retrieval is lexical (FTS5, no stemming), so the packet has
   `"memory_items":[]` and a first-time user concludes it does not work.
5. **Validation errors do not say which field failed.** A 301-character title, a blank title, or
   `--importance 500` all print `error[invalid_input]: Memory input failed schema validation`
   (CLI) or `{"detail":"Memory input failed schema validation"}` (API). The user has to read the
   source to find the 300-character and 0-100 limits.
6. **API errors carry no stable code.** The CLI prints `error[project_not_registered]: ...`, but
   the API returns `{"detail": "..."}` with only a status, and uses 400 for an unregistered
   project and 404 for a missing memory. An agent cannot branch on the cause. `ErrorResponse` in
   `api/schemas.py` exists but is unused.
7. **No context endpoint in the HTTP API.** Building a context packet, the core feature, is
   CLI-only; `GET /v1/context` is 404.
8. **`--project` must be the exact registered root.** From a subdirectory, `--project .` fails
   with `project_not_registered`; there is no default to the current directory. Agents usually run
   in subdirectories.
9. **Database errors have no next step.** A corrupted file prints
   `Database initialization failed: file is not a database`; a database from a newer AI Bridge
   prints `Applied migration 3 is missing from the package`. Neither names the database path or
   says "upgrade AI Bridge" / "move the file aside". `aibridge doctor` fails the same way, so the
   diagnostic tool cannot diagnose.
10. **Thin help text.** `--importance`, `--volatility`, `--confidence`, `--subject`,
    `--max-chars` have no help and no bounds in `--help`; `serve` promises a "web shell" that does
    not exist; there is no `--version`; the API reports a hard-coded `0.1.0`.
11. Smaller items: `run-show <unknown>` reports `invalid_input` instead of a not-found code;
    re-registering a path with a new `--name` silently keeps the old name; API endpoints have no
    descriptions or examples on `/docs`; `GET /` is 404 instead of pointing at `/docs`; the
    candidate's `applied_memory_id` is kept in the event log but not in the `memory_candidate`
    table, so `candidate list` never shows which memory an approval produced.

Performance is not a problem at this size: CLI start-up plus one command is ~0.27 s; 250 memory
adds through the service take 0.77 s; `context build` over 250 matching memories takes 0.57 s.

## Ranking

Impact is for a developer or agent hitting it in normal use; effort is S (< 1 h), M (half a day),
L (more).

| Rank | Finding | Impact | Effort | Plan |
|---|---|---|---|---|
| 1 | 1 + 6: tracebacks/500s, no API error codes | High | S | Phase 2 |
| 2 | 2: non-atomic candidate approval | High (data integrity) | M | Phase 2 |
| 3 | 3: export truncates at 100 | High (silent data loss in output) | S | Phase 2 |
| 4 | 4: README quick start | High (first impression) | S | Phase 2 |
| 5 | 5: validation errors without field | Medium | S | Phase 2 |
| 6 | 9: database errors without next step | Medium | S | Next |
| 7 | 10: help text, `--version` | Medium | S | Next |
| 8 | 7: context endpoint | High | M | Next |
| 9 | 8: `--project` from subdirectories / cwd default | Medium | M | Next |
| 10 | 11: smaller items (incl. `applied_memory_id` column, needs a migration) | Low-Medium | S-M | Next |
