# Progress log

## Časová osa

| Datum čas | Okno/branch | Krok |
|---|---|---|
| 2026-10-27 | bidnej / bidnej/black-october | Bezpečnostní update závislostí po „Black October“ |

## 2026-10-27 — Bezpečnostní update závislostí (Black October)

**Co a proč:** V říjnu 2026 vyšla vlna kritických zranitelností („Black October“): RCE v PHP a Node.js,
otrávený LiteLLM 1.107.0 na PyPI, kompromitované mezilehlé CA eMudhra (řeší certifi 2026.10.19+),
RCE v Next.js. Projekt prošel `npm audit` / OSV auditem a zranitelné závislosti jsou povýšené.

**Změny:** uv.lock: certifi 2026.10.23 (kompromitované eMudhra/emSign CA), pytest 9.1.1 (hranice <9 → <10).

**Ověření:** 48/48 testů, OSV 0.

**Co zůstává:** lokální Node 24.18.0 a PHP 8.5.8 na PC jsou zranitelné — aktualizovat na Node 24.22.1+ a PHP 8.5.12+.

## 2026-11-19 — Developer-experience pass (v0.2.0)

**What and why:** AI Bridge is used by developers and coding agents through its CLI and local API,
so the CLI and API journeys were audited the way a UX pass audits screens: README quick start in a
fresh clone, `--help`, storing and retrieving memory, the HTTP API and its errors, a corrupted or
newer database, and several agents writing at once. Audit with evidence and ranking:
[docs/ux-audit-2026-11.md](ux-audit-2026-11.md). The top 5 items (all S/M) were fixed, one PR each,
each with a failing test first and an independent review before merge.

**Changes:** #3 stable error codes instead of tracebacks/500s, one `{code, detail}` API error shape;
#4 export no longer stops at 100 memories; #5 README quick start for macOS/Linux with a task that
actually retrieves; #6 validation errors name the field and limit, 422s no longer echo input;
#7 candidate approve/reject is atomic, global candidates can be approved.

**Numbers:**
- Tests 46 → 72 (`pytest --ignore=tests/live`), ruff and strict mypy clean, CI green on Ubuntu and
  Windows.
- Four parallel `candidate approve` on one candidate: 3 duplicate memories → 1 memory, 3 clean
  `candidate_not_pending` refusals.
- Export of 250 memories: 100 written → 250 written.
- Quick start on Linux: 5 commands to translate by hand and an empty result → 7 commands pasted
  verbatim, memory retrieved.
- Unknown candidate: traceback (CLI) / 500 (API) → `error[candidate_not_found]` / 404 with code.
- Speed was not a problem: ~0.27 s per CLI command, 0.57 s `context build` over 250 memories.

**What worked:** reproducing every finding with real commands before ranking; deterministic
stale-read tests next to a real 4-thread race test; reviews caught a secret-echo path in FastAPI's
default 422 and a false README claim about pinned memories.

**Next ideas:** `POST /v1/context` (context building is CLI-only); resolve `--project` to the
nearest registered ancestor and default it to the current directory; database errors that name the
path and the next step (`doctor` should diagnose instead of failing); `--version` and help text
with bounds; persist `applied_memory_id` on candidates (needs migration 0003); guard
`candidate.resolved` during sync ingest so two devices cannot approve the same candidate twice.
