# Code Design Notes

## #212 — user-defined providers (any OpenAI-compatible endpoint)

**Problem:** provider names were hardcoded (deepseek/zai/github) in config,
API, verification, and UI; users could not add providers or select between
them at runtime.

**Design:**
- `ProviderDef` (config.py): `{api_key?, base_url?, env_var?}`; stored as
  `[providers.<name>]` tables in config.toml; legacy string shorthand kept.
- Key resolution: `provider_effective_key(name, def)` — env var
  (`env_var` or legacy name or `<NAME>_API_KEY`) wins over stored `api_key`;
  `apply_provider_keys` setdefaults it into the environment at load.
- Model resolution (`engine._model_from_name(name, base_url, providers)`):
  1) prefix matches a provider def with `base_url` → `OpenAIChatModel` on
     `AsyncOpenAI(base_url)` (works for any OpenAI-compatible API);
  2) `zai:` + `fallback_base_url` → dedicated ZaiModel (coding-plan endpoint);
  3) else pydantic-ai `infer_model` (all native providers).
- Validation relaxed: any `x:y` model ref is accepted (ModelLineupIn).
- API: `models_payload` adds `provider_defs` (base_url/env_var, no secrets)
  and `provider_prefixes` (suggestion list); `save_provider_keys` accepts
  per-entry string (key), table (full def merge), or null (delete);
  SECRET_MASK sentinel contract unchanged. `/models` also returns
  `provider_prefixes` for the run composer.
- Verify: generic per-provider smoke against its base_url; legacy trio keep
  default endpoints; no-base_url providers report `ok: null` "not tested".
- UI: Config tab renders dynamic provider rows (key/base_url/env_var,
  clear/remove) + add row; lineup fields get a provider-prefix datalist;
  run composer model selector now sends real `provider:model` strings
  (previously sent slot names, which never resolved).

**Impact:** config.py, engine.py, worker.py, server.py, App.jsx, README.
Config loads per run — provider changes apply from the next run, no bounce.

**Fail-safe:** unknown provider-table shapes warn+skip; bad PUT payloads are
validated before any write; `provider_effective_key` falls back to
`'not-set'` key so construction errors surface at run time, not boot.

## PRDs & Tech Designs — general planning docs (DB-backed, UI-surfaced)

**Problem:** planning surface had roadmap/tickets/decisions but no
requirements (WHAT/WHY) or technical-design (HOW) artifacts; agents jumped
from conversation straight to tickets.

**Design (user-chosen: DB-backed like tickets, surfaced in web UI):**
- Schema (db.py, additive): `prds` (status draft|active|sunset) and
  `tech_designs` (status draft|approved|superseded, optional `prd_id` FK-ish
  link for requirements traceability). Both workdir-scoped.
- RoadmapStore: list/create/update/delete for prds + designs; constants
  PRD_STATUSES / DESIGN_STATUSES.
- Agent tools (build_roadmap_toolset): create_prd/read_prd/update_prd,
  create_tech_design/read_tech_design/update_tech_design; list_planning now
  shows PRDs and Tech designs sections. Approved designs are superseded,
  never rewritten (tool docstring states this).
- Server: GET /planning returns prds+designs; POST/PUT/DELETE
  /planning/prds[/{id}] and /planning/designs[/{id}], mirroring decisions
  endpoints (422 on bad status, 404 on unknown id).
- Frontend: Prd/TechDesign types + api methods; Planning tab gets PRDs and
  Tech designs sections with status selects and add-kind options.
- Skills (general, in .codingdude-seed/skills): `prd` (WHAT/WHY doc,
  REQ-<n> numbering, mandatory Non-Goals + Open Questions, feeds roadmap/
  tickets) and `tech-design` (HOW doc, REQ traceability table, alternatives,
  supersedes-not-rewrites, hard trade-offs still go to record_decision).
  Positioned explicitly against to-spec/grilling/grill-with-docs.

**Impact:** additive schema (CREATE TABLE IF NOT EXISTS — no migration
needed); /planning response gains two keys (frontend tolerates absence via
optional chaining); no existing tool signatures changed.

## GitHub issue auto-mirror (R53) — convention enforced in code

**Problem:** the dual-logging convention (local planning item first, then a
mirrored GitHub issue) lived only in agent memory/skills; sessions drifted
and backfills were needed repeatedly.

**Design:** enforcement moved into the store, not agent discipline.
- `gh_mirror.py` (new): `GitHubMirror` — best-effort `gh` CLI boundary.
  Availability probed once per process per workdir (gh on PATH, github.com
  origin remote, gh auth ok), cached at class level. `create_issue` parses
  the issue number from the returned URL; `close_done` closes as completed
  and applies the green `done` label (label ensured once). Every failure
  logs one line and returns None/False — never raises, never blocks.
- `db.py`: additive `gh_mirror` mapping table (workdir, kind
  ticket|roadmap, local_id, issue_number) so closes reach the right issue.
- `roadmap.py`: `RoadmapStore(db, mirror=None)` — create_ticket and
  create_roadmap_item (DB rows) mirror on create; update_ticket/update_
  roadmap_item mirror-close on `done`. The agent toolset md-path
  (ROADMAP.md items) mirrors too, keyed by R-id. Single choke point covers
  agent tools, server endpoints, and execution.py ticket closes.
- `config.py`: `[planning] github_mirror` (default true) disables the
  mirror entirely.

**Impact:** additive schema + new module; no existing tool signatures
changed; local writes unaffected when gh/GitHub is unavailable (skips with
one log line). Tests mock the gh boundary (FakeMirror) — no network.

## Docker install-path verification (R56)

**Problem:** setup scripts (`setup-codingdude.bat`, `gates.bat`) were only
ever exercised on the dev Windows machine; unverified whether the pinned
lockfile, package build, frontend build, home seeding, and server boot all
work from a bare machine.

**Design:** `docker/Dockerfile.verify` — python:3.12-slim + uv + Node.
Build: `docker build -t codingdude-verify -f docker/Dockerfile.verify .`
(context trimmed by `.dockerignore`: no .git, caches, .venv,
node_modules, dist, DBs, logs). Installs the Linux equivalent of setup:
`uv sync --frozen`, then `npm ci && npm run build`; boots
`codingdude.cli serve`. Gates (ruff/pytest/mypy) run
interactively (`docker run codingdude-verify uv run pytest -q`) because
full pytest OOM-kills the default docker build sandbox. Semgrep is not
installed in the image, so the in-container security gate runs in its
degraded bandit/regex mode (as setup-codingdude.bat warns when semgrep
is absent).

**Verified findings (2026-10):**
- `uv sync` needs the full source (incl. README.md) — no pre-source
  dependency-only layer is possible with the uv-build backend.
- ruff clean; mypy reports 2 Linux-only typeshed false positives
  (restart.py Windows `creationflags`, code correctly `os.name`-guarded).
- pytest: 765 passed / 9 failed / 7 skipped — all 9 failures
  platform-specific (docker CLI absent in container, `gh` stub path,
  Windows process-tree semantics in restart/run-captured tests).
- Server boots on Linux, seeds `~/.codingdude`, `/health` ok (v0.4.0),
  serves the freshly built UI (logo + JS/CSS assets 200). Server binds
  127.0.0.1 by design, so health is checked via
  `docker exec <name> curl -sf http://127.0.0.1:8765/health`.

**Impact:** additive `docker/Dockerfile.verify` + `.dockerignore`; no source
changes. Genuinely Windows-only setup steps (winget gh, github-mcp.exe)
don't apply on Linux by design; codegraph (`npm i -g`) is
platform-independent but was not installed in the verify image.

## Stale artifact expiry (R58) — retiring orphaned choice/spec cards

**Problem:** `ArtifactStore.emit_choice_card` / `emit_spec_block` write a row
with `status='pending'`; the chat card and the Artifacts tab render every
row that is not `answered`. Nothing retires a card when its run is stopped,
crashes, or simply ends unanswered, so dead cards accumulate and reappear at
every boot (7 found on the remote install, 2026-09-28 → 2026-10-10). The
only way to clear one from the UI was to pick a bogus option, which then
wrote a fake answer into decision history.

**Design:** add a terminal state rather than reusing `answered` — a
dismissed card recorded no answer, and inventing one corrupts the audit
trail. Dismissal is **user-driven only**: nothing expires a card
automatically, because silently hiding a question the user has not read
yet is worse than a stale card.
- `artifacts.py`: `dismiss(artifact_id)` → `status='dismissed'` (KeyError on
  unknown id, ValueError if already terminal); `respond()` raises
  ValueError on a dismissed artifact so a stale card cannot be resurrected.
  `feedback()` is unchanged — it already returns None for any status other
  than `answered`, so the agent's replacement sees nothing.
- `server.py`: `POST /artifacts/{artifact_id}/dismiss` (404 unknown, 422
  non-pending), mirroring the respond endpoint. `start_run` deliberately
  does *not* sweep pending cards.
- `App.jsx`: dismiss button on each pending card in the chat column and in
  the Artifacts tab; choice buttons disabled for any non-pending status and
  a dismissed spec block renders its markdown read-only.
- `artifacts.ts`: unchanged — `pendingArtifacts` already filters
  `status === 'pending'`, so dismissed rows never surface in chat.

**Impact:** no schema change (status is a free-text column; the SSE `watch`
loop emits its `answered` delta for any status transition, so dismissal
propagates live). Existing `answered` cards are untouched, and re-answering
an `answered` card stays allowed — only `dismissed` is closed. Not covered
by design: a card is not auto-retired when its worker dies mid-run; the
user dismisses it (or answers it, which still works if the run is alive).

## R59 — Dynamic dockable workspace (P0: frontend decomposition)

**Goal.** Users arrange panels themselves (drag to split/merge/float, popout,
persisted layout). Engine: `dockview-react` 8.6.1, MIT, pinned exactly — see
tech design #1 and design decision #94. P0 is the prerequisite: `App.jsx` was
a 3288-line monolith, and docking needs each surface to be an independently
mountable panel.

**P0 structure** (`frontend/src/`, move-only — no behaviour change):

| Module | Contents |
|---|---|
| `ui.jsx` | `Mermaid`, build constants (`UI_VERSION`/`UI_BUILD`/`UI_SHA`), `shortStamp` |
| `chrome/` | `ErrorBoundary` (imported by `main.jsx`), `Login`, `Sidebar`, `AgentStrip`, `StatusFooter` — the surfaces that stay fixed |
| `cards/chatCards.jsx` | `ToolTimeline`, `EditBlock`, `AskUserCard`, `PendingArtifactCard`, `ApprovalCard`, `PlanCard` |
| `store/useFileWorkspace.js` | shared tab/draft/dirty/diff state |
| `panels/` | `Explorer` (TreeNode + FileTree), `Editor` (EditorPane), `Chat`, `Prompt` |
| `panels/dock/` | `Terminal`, `Notes`, `Artifacts`, `ModelsConfig` (+`CfgTextField`/`CfgNumField`), `Planning`, `Standards`, `Diff` (`DiffPanel`) |

**Why `cards/` groups six components in one file:** they share one lifecycle —
they appear mid-run and settle with the run — and the codebase already
precedent-sets this in `CodeEditor.jsx` (exports `CodeEditor` + `CodeDiff`).

**Deliberate remainder.** `Graph`, `Output`, `Waterfall`, `Trace`, `Cost`,
`MCP`, `Renders` and `Processes` stay inline in `DockPanel`: all eight read
its single shared poll through `data`/`setData`/`selRun`. Extracting them
move-only would thread those props through nine files — work P2's data store
deletes. They move in P2, each with its own visible-subscriber subscription.

**Impact.** `App.jsx` 3288 → 1337 lines and now holds only `DockPanel` plus
`App` (session/SSE state machine + layout). No API, DB, or behaviour change.
Tests do not touch `App.jsx` (all 91 cover pure `src/*.ts` helpers), so the
gates are `npm run build`, `eslint src`, and a manual visual parity pass —
documented in `RESCUE.md`, which is the recovery sheet for this refactor.
Two pre-existing gaps found during P0 were **left alone by P0 (move-only) and
then fixed under their own tickets**: the `Processes` tab body was unreachable
(`Processes` missing from the `tabs` array — #227) and `Memory` polled
`/memory` with no body branch (plus it was gated on a session it does not
need — #228). Both are behaviour changes, so they are separate commits from
the move-only ones and both got a full build/lint/91-test pass.