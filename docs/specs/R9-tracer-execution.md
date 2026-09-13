# R9 Tracer — Resumable long-horizon work (`ticket_execution`)

Tracer bullet: crash-safe ticket claims with attempt lineage, per-step
verification evidence, and a resume-state read as the agent's first move.

## Design

New `src/codingdude/execution.py` — `ExecutionStore(db, workdir)`, mirroring
`RoadmapStore` (direct `db._conn`, workdir-scoped rows).

New table `ticket_execution` in `db.py::_SCHEMA`:

    id INTEGER PK, ticket_id INT NOT NULL, workdir TEXT NOT NULL,
    session_id TEXT NOT NULL, status TEXT CHECK IN
    ('claimed','released','done','stale') DEFAULT 'claimed',
    plan_json TEXT NOT NULL DEFAULT '[]',
    steps_json TEXT NOT NULL DEFAULT '[]',
    heartbeat_at TEXT NOT NULL, created_at TEXT NOT NULL

- `steps_json`: `[{"text": ..., "status": "todo|done", "evidence": ...}]`.
  Evidence is the verification output a step shipped with (test count, command).

### Store API
- `claim(ticket_id, session_id, plan_steps=None, stale_after_s=900)` → attempt
  dict. Crash-safe: an existing `claimed` attempt on the same ticket is
  - same session → reuse it (idempotent),
  - another session with fresh heartbeat → `ValueError('claimed by ...')`,
  - another session with stale heartbeat → marked `'stale'`, new attempt opened.
- `heartbeat(attempt_id)` → refresh `heartbeat_at`; unknown id → `KeyError`.
- `set_step(attempt_id, index, status, evidence=None)` → updates step; also
  updates the ticket's own status to `in_progress` in the same commit.
  Out-of-range index → `ValueError`.
- `release(attempt_id, status='released')` → terminal status
  (`released`|`done`); done stamps ticket `done` (existing `update_ticket`
  path records HEAD sha).
- `resume_state(ticket_id)` → latest attempt dict (any status) or `None`.
  This is the "first move": claimed-by, plan, step progress + evidence.

### Agent tools (`build_execution_toolset(store, session_id)`)
- `claim_ticket(ticket_id, plan_steps)` → claim or readable conflict message
- `update_execution_step(index, status, evidence)` → progress + evidence
- `release_ticket(status)` → `'done'`|`'released'`
- `get_resume_state(ticket_id)` → formatted state or "no execution history"
- `heartbeat_claim()` → keep-alive

Wired into `plugins.build_all` next to the roadmap toolset. No SSE, no UI
changes — Planning tab already shows ticket status which now reflects
in_progress via step updates. Non-goals: cross-machine leases, automatic
work-stealing, plan diffing.

## Tests (`tests/test_execution.py`)
Seams: `ExecutionStore` and `build_execution_toolset` over real SQLite
(`Database.connect(tmp home)`), no mocks.
1. claim creates attempt; duplicate claim by same session reuses attempt
2. conflicting fresh claim raises with claiming session id
3. stale claim (heartbeat older than TTL) → old attempt marked stale, reclaim opens new attempt
4. set_step updates step + evidence and flips ticket to in_progress; bad index raises
5. release('done') closes attempt and ticket
6. resume_state returns latest attempt with steps/evidence; unknown ticket → None
7. toolset: claim → step → heartbeat → release round-trip; conflict message readable
