# AI Bridge implementation plan

## Product direction

AI Bridge is intended to become a personal AI development control plane. Its durable
differentiator is provider-independent, selective knowledge transfer rather than another terminal
or multi-agent UI.

## Delivery sequence

1. **Memory kernel (current):** stable identities, append-only change events, SQLite projection,
   FTS5 retrieval, bounded context packets, and an inspectable CLI.
2. **Cross-agent loop:** candidate validation, provenance verification, secret scanning, and Claude
   and Codex adapters. The deterministic contract proof is complete; a credentialed opt-in
   live hand-off acceptance test remains required.
3. **Local control plane:** versioned API, conversations, tasks, run events, artifacts, and web UI.
4. **Development workbench:** isolated Git worktrees, diff/test panels, and approval-gated GitHub
   mutations.
5. **Adaptive orchestration:** capability-based routing, usage policies, and independent review.
6. **Knowledge network:** edges, staleness, consolidation, and benchmark-gated semantic retrieval.
7. **Native integrations:** MCP, supported hooks, and a versioned plugin surface.
8. **Encrypted sync and mobile companion:** E2E event sync through a ciphertext-only relay.
9. **Hardening:** encrypted storage, backup/restore, revocation, installers, and signed releases.

## Architectural invariants

- Domain/application code depends on ports, never SQLite, subprocesses, or a provider SDK.
- SQLite is the canonical local projection; Markdown is documentation/export only.
- Every projection mutation and its immutable `change_event`/outbox record commit atomically.
- Project identity is a UUID; device-specific paths live only in `project_mount`.
- Retrieved memory is untrusted data and is always bounded before entering an agent prompt.
- Future capability is represented through stable interfaces and schemas, not empty applications.
