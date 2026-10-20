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
(context trimmed by `.dockerignore`: no .venv, node_modules, dist, .git,
DBs). Runs the Linux equivalent of setup: `uv sync --frozen`, ruff, then
`npm ci && npm run build`; boots `codingdude.cli serve`. Gates run
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