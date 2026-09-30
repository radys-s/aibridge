# ADR 0001: SQLite projection backed by append-only change events

- Status: Accepted
- Date: 2026-09-15

## Context

AI Bridge needs durable, inspectable local memory now without blocking future encrypted multi-device
sync. Pure Markdown lacks transactional constraints and reliable full-text retrieval. A graph or
vector database would add operational cost before retrieval benchmarks justify it.

## Decision

Use Python's SQLite driver as the canonical local projection. A mutation writes its immutable
`change_event`, sync outbox entry, and projection rows in one `BEGIN IMMEDIATE` transaction. Public
identities are UUIDs. Device paths are mounts rather than project identity. Event envelopes and
payloads are versioned, discriminated, deeply immutable Pydantic models with origin metadata. FTS5
is a manually maintained projection because `trusted_schema=OFF` intentionally prevents relying
on schema-side automation.

Connections enable foreign keys, WAL, a busy timeout, and `trusted_schema=OFF`. Startup probes the
actual FTS5 capability. A serialized initializer validates a contiguous migration sequence and the
stored filename and SHA-256 checksum before applying anything. SQL triggers reject updates and
deletes of memory revisions and change events; the item points to its current revision. A composite
foreign key prevents project-scoped memory from crossing its project's space.

Projection rebuild and remote ingestion are separate operations. Rebuild accepts already typed
events for an empty projection. Remote ingestion validates each envelope, applies supported events
without adding them to the outbound queue, and stores only a payload hash plus a non-sensitive
reason when quarantining invalid input.

## Consequences

- A local event stream can later be encrypted and synchronized without replacing domain models.
- Projection rebuilds are deterministic for supported events.
- Inbound events are idempotent and cannot create synchronization echo loops.
- Invalid future or malformed event payloads cannot bypass domain validation or persist raw secrets
  through quarantine.
- Repository code must update FTS and relational rows together and test their integrity.
- SQLCipher, semantic indexing, and a relay remain replaceable adapters, not Phase 1 dependencies.
