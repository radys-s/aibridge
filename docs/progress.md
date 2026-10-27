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
