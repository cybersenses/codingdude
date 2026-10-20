# CodingDude — Technical Design Manual

**Status:** living document · **Hierarchy:** [PRD.md](PRD.md) (why/what) →
[TECH-DESIGN.md](TECH-DESIGN.md) (system summary) → **this manual** (full
technical detail) → [adr/](adr/) (decisions) → [specs/](specs/) (per-feature)

This manual describes the system **as built**, with each claim anchored to the
implementing module. The companion [USER-MANUAL.md](USER-MANUAL.md) covers
operator-facing behavior.

---

## 1. Architecture overview

```
 Browser (React/Vite SPA, frontend/src)
    │  SSE (run events, artifacts) + HTTP JSON (auth, config, sessions)
    ▼
 Server (server.py — FastAPI/uvicorn, loopback-only)
    │  spawns one subprocess per run; bridges worker WebSocket ⇄ browser SSE
    │  persists sessions/messages/runs/artifacts/planning to SQLite (db.py)
    ▼
 Worker (worker.py — python -m codingdude.worker)
    │  builds config, constructs the engine, streams trace events
    ▼
 Engine (engine.py — pydantic-ai agent loop)
    │  tool calls (workdir-contained)          │ MCP servers / plugins
    ▼                                          ▼
 Filesystem · shell · git · gh            LLM providers (user-configured)

 Headless (cli.py `run`) — the same engine in-process, no server/worker.
```

Three process roles:

1. **Server** — never runs the agent itself (ADR-0002). Owns HTTP/SSE,
   auth, persistence, run registry, and worker supervision.
2. **Worker** — one subprocess per run; connects back over a local
   WebSocket; dies with its run. Shares the same SQLite DB and config home.
3. **Engine** — the pydantic-ai agent loop; shared by worker and headless
   paths (`run_pipeline.py` orchestrates a full run: onboarding, context,
   memory, planning, toolsets, gates, memory-extraction tail).

## 2. Module map (`src/codingdude/`)

| Module | Responsibility |
|---|---|
| `server.py` | FastAPI app factory (`create_app`), all HTTP/SSE/WS endpoints, static dist serving, run channels, janitor |
| `worker.py` | Per-run subprocess; dials the server WS, applies project `[models]` overrides, runs the pipeline, streams events |
| `engine.py` | Agent construction: model resolution, toolsets, approvals, budget, failover |
| `run_pipeline.py` | Full-run orchestration (onboarding, context assembly, planning loop, gates, post-run tail) |
| `cli.py` | `run` (headless), `serve`, `restart`, `eval` subcommands |
| `config.py` | `config.toml` load/save (`load_config`, `save_models`, `save_provider_keys`), `apply_project_models` overlay, key resolution + verification |
| `db.py` | SQLite schema + `Database` (WAL, per-home) |
| `tools.py` | Core toolsets: file ops (`resolve_workdir_path/_file` containment, `_atomic_write`), shell (env scrubbing), git, web, delegation, coverage, knip, CI, audit, ask-user |
| `ast_tools.py`, `callgraph.py`, `cfg.py`, `structure.py`, `impact.py`, `deadcode.py`, `mutation.py`, `fuzzing.py`, `bench.py` | Analysis tools (AST rename/references, call graphs, control-flow, structure, impact, dead code, mutation, API fuzzing, benchmarks) |
| `roadmap.py` | Planning store: roadmap items, tickets, decisions, PRDs, tech designs (+ agent tools, ROADMAP.md parser/upserter) |
| `planning.py` | Plan store + step tracking for the planning loop |
| `approvals.py` | Tiered approval engine (interactive cards, pattern approvals, always-gated set) |
| `memory.py` | MemoryStore: keyword + semantic retrieval, embeddings, referential solutions |
| `skills.py` | SkillRegistry: SKILL.md discovery, progressive disclosure, save/delete |
| `directives.py` | Directive layering (global DIRECTIVES.md + project AGENT.md) |
| `onboarding.py` | First-contact project scan; conventions detection feeds the onboarding block |
| `checkpoints.py` | CheckpointStore: file snapshots, restore/rewind |
| `artifacts.py` | ArtifactStore: choice/spec/decision/HTML cards + SSE watch |
| `processes.py` | Shell process tracking (R28) |
| `sandbox.py`, `worktrees.py`, `delegation.py` | Sandboxed delegation and git worktrees |
| `mcp_config.py` | `mcp.json` merge (global + project), per-server disable, default seeding |
| `codegraph_boot.py` | Boots the per-project tree-sitter codegraph index |
| `security.py` | Security gate (Bandit, Semgrep, secret regexes) — fails closed |
| `telemetry.py`, `traces.py`, `evals.py` | Usage/cost accounting, JSONL traces, scenario recording/replay |
| `scaffold.py`, `seed.py` | Project scaffolding; `~/.codingdude` seeding (skills, checklists) |
| `vision.py`, `research.py`, `references.py`, `guidance.py`, `projectnotes.py`, `restart.py`, `plugins/` | Vision tools, research pipeline, reference manual store, guidance notes, notes, restart, plugin hook |

## 3. Server design (server.py)

### 3.1 Auth & binding

- `HOST = '127.0.0.1'` only. `authorize` accepts Bearer header, `cd_session`
  cookie, or `?token=` (EventSource) — all compared to the stable token from
  `~/.codingdude/server-token` (`load_or_create_token`).
- Browser login is passwordless: `POST /auth/local` attests same-origin +
  loopback client (`Sec-Fetch-Site`, Host allowlist, origin check) before
  granting the cookie. `POST /login` accepts the token as a password.
- `GET /health` is unauthenticated: `version` (package metadata), `git_sha`,
  `started_at` (stale-server detection).

### 3.2 Run channels

`RunChannel` is the server-side hub per run:

- `history` (capped 5000 events) — replay for late/reconnecting subscribers.
- `subscribers` — asyncio queues; every subscriber gets the full stream
  (broadcast semantics; no consumer can starve another of the terminal).
- `inbox` — server → worker messages (approval responses, ask_user answers).
- `worker` — the Popen handle; `boot_seen`, `reaped` for lifecycle flags.

Lifecycle guarantees:

- **One live worker per session**: starting a new run terminates any live
  worker for that session and pushes `RUN_CANCELLED` to old viewers.
- **Reaper** (`_reap_worker`): after the worker's WS closes, waits for
  process exit; if no terminal event was delivered, synthesizes `RUN_ERROR`
  (`worker_died`). Records the run end state. Idempotent.
- **Janitor** (`_run_janitor`, #148): 2s sweep independent of the WS
  lifecycle — reaps exited workers; terminates live workers that never
  connected within 60s (`_BOOT_TIMEOUT_S`).
- **Terminal replay grace**: a channel with a delivered terminal stays
  registered 300s so EventSource auto-reconnects replay and settle.
- **Boot reconciliation**: at startup, runs still marked `running` become
  `interrupted`; dead process rows get durable end states.
- Prompts travel via a file (`~/.codingdude/prompts/<run_id>.prompt`), not
  argv — Windows 32k command-line limit. Stale prompt files older than 24h
  are cleaned at boot.

### 3.3 Endpoint reference

All endpoints under the loopback server; `/api/...` prefix is stripped
(dev-proxy convention of the built frontend).

**Auth:** `GET /auth/check`, `POST /auth/local`, `POST /login`
**Sessions/runs:** `POST /sessions`, `GET /sessions?workdir=`,
`GET /sessions/{id}/messages`, `POST /sessions/{id}/runs` (spawns worker),
`GET /runs/{id}/events` (SSE), `GET /runs/{id}/alive`, `POST /runs/{id}/approve`,
`POST /runs/{id}/ask`, `DELETE /runs/{id}` (cancel), `GET /runs/active`,
`WS /runs/{id}/ws` (worker dial-back)
**Session inspection:** `/sessions/{id}/` + `runs`, `trace?limit=`,
`usage`, `diff`, `files`, `tree`, `file?path=`, `PUT file` (mtime staleness
guard, 409 on conflict), `file_diff`, `callgraph?path=`, `archmap`,
`trust?path=`, `cfg?path=&function=`, `structure`, `processes`, `renders`,
`render?path=`, `plan`, `review` (short-lived `--review` worker), `standards`
**Notes:** `POST/GET /sessions/{id}/notes`; `POST/GET /notes?workdir=`,
`POST /notes/{id}/resolve`, `DELETE /notes/{id}` (project notes)
**Artifacts:** `GET /sessions/{id}/artifacts`, `/artifacts/events` (SSE),
`POST /artifacts/{id}/respond`
**Projects:** `GET/POST /projects`, `DELETE /projects/{id}` (creation runs
scaffold + codegraph boot, results in the response)
**Planning:** `GET /planning?workdir=`; CRUD under `/planning/roadmap`,
`/planning/tickets`, `/planning/decisions`, `/planning/prds`,
`/planning/designs` (empty PUT → 422 "nothing to update"; unknown ids → 404;
PRD delete severs `prd_id` links on designs)
**Checkpoints:** `GET /sessions/{id}/checkpoints`,
`POST /checkpoints/{sid}/{cp}/restore`, `POST .../rewind`
**Config:** `GET /models`, `GET/PUT /config/models` (secrets masked;
SECRET_MASK sentinel on write), `GET /config/verify` (per-provider auth smoke)
**Self-hosting:** `GET/PUT /directives`, `GET /skills/detail`,
`PUT/DELETE /skills/detail/{name}`, `GET /checklists[/name]`
**Memory/MCP:** `GET/POST /memory`, `DELETE /memory/{id}`, `GET /mcp`,
`POST /mcp/{name}/toggle`
**Terminal:** `POST /sessions/{id}/exec` (120s capture cap, 8k output)

### 3.4 Static serving

If `frontend/dist` exists it is mounted at `/` (html mode) — single-command
deployment. The frontend bakes `__APP_VERSION__` at build; backend version
comes from package metadata.

## 4. Worker & engine

### 4.1 Worker (`python -m codingdude.worker`)

Args: `--server <ws-url>`, `--session`, `--workdir`, `--prompt-file`,
`--run-id`, `--model`, `--yolo`, `--fix-loop`, `--budget`, `--image`.
Authenticates to the WS with the `CODEDUDE_WORKER_TOKEN` env var. Applies
per-project `[models]` overrides from the workdir's config, constructs the
engine, runs the pipeline, streams every event over the WS, and performs the
post-run memory-extraction tail before exiting.

### 4.2 Engine (engine.py)

- **Model resolution seam** `_model_from_name(name, base_url, providers)`:
  (1) `provider:` prefix matching a user ProviderDef with `base_url` →
  `OpenAIChatModel` on `AsyncOpenAI`; (2) `zai:` + coding-plan
  `fallback_base_url`; (3) pydantic-ai `infer_model` for native providers.
- **Key resolution**: `env_var` → legacy name → `<NAME>_API_KEY` env vars win
  over stored `api_key` values.
- **Failover**: main → fallback on model errors; budget enforcement hard-stops.
- **Toolsets** assembled in `tools.py` (`build_toolset` + sub-toolsets:
  shell, git, web, delegation, coverage, knip, CI, audit, ask-user) plus
  analysis, planning, memory, skills, checkpoint, process, artifact, vision,
  research, reference, guidance, sandbox/worktree toolsets from their modules.
  All file-path tools route through `resolve_workdir_path/_file` containment;
  writes use `_atomic_write`.
- **Approvals** (approvals.py): tiered; relayed to the UI as cards via the
  channel inbox; pattern approval session-scoped; always-gated set (push, PR,
  release, destructive fs). Headless: gated action aborts (exit 2) unless
  `--yolo`; budget stop exits 3 regardless.
- **Subprocess hygiene**: `scrubbed_env` strips KEY/TOKEN/SECRET/PASSWORD/
  CREDENTIAL variables; shell runs via `shell_argv` (Git Bash resolution on
  Windows); `_kill_tree_sync` for tree-wide termination.

## 5. Data model (db.py)

SQLite under the config home (WAL). Tables (all `CREATE TABLE IF NOT EXISTS` —
additive; new columns need migration care):

sessions, messages, session_notes, project_notes, approvals, memory, usage,
embeddings, plans, projects, roadmap_items, tickets, ticket_execution,
reference_sections, reference_meta, artifacts, renders, processes, runs,
design_decisions, prds, tech_designs.

Notes:

- `runs` has a status CHECK constraint; `record_run_end` maps RUN_CANCELLED →
  `'interrupted'` (not `'cancelled'`) to satisfy it.
- Traces are JSONL files per session (`~/.codingdude/traces/<session>.jsonl`),
  not a table.
- Planning: ROADMAP.md in the workdir is canonical when present —
  `GET /planning` parses it directly; DB fallback otherwise. PRDs/tech
  designs are DB-only, keyed by workdir; designs carry an optional `prd_id`.

## 6. Frontend (frontend/src)

React + Vite + Tailwind SPA; `api.ts` is the typed HTTP layer. Chat pane with
approval/plan/choice/spec/artifact cards; left rail: sessions, file tree,
Monaco editor (save honors the mtime staleness guard). Right panel tabs
(listed in USER-MANUAL §7) consume the endpoints in §3.3 one-to-one. SSE is
used for run events and artifact deltas. Tests: vitest; build output is
`frontend/dist`, served by the server.

## 7. Security architecture

Summary of ADR-0004 posture, as implemented:

- Loopback-only bind; token auth on everything except `/health`; browser
  attestation for passwordless login.
- Tiered approvals with an always-gated core; pattern approvals
  session-scoped only.
- Budget cap hard-stop independent of `--yolo`.
- Env scrubbing on all subprocesses; secrets masked in every config read
  path; security gate (Bandit + Semgrep + secret regexes) fails closed.
- File tooling workdir-confined (`resolve_workdir_path`); the UI editor and
  render/file endpoints use the same containment.
- Known limits: the shell tier check is a heuristic, not a sandbox; approved
  commands run with full user permissions; web fetch permits localhost
  probing. Deferred: job-object/container isolation, per-command env
  allowlists.

## 8. Extension points

| Extend by | How |
|---|---|
| New LLM provider | config-only (`[providers.name]` with `base_url`); no code |
| New MCP server | `mcp.json` (global or project); per-session enable/disable |
| New skill | `SKILL.md` dir in `~/.codingdude/skills/` or project skills; editable in the UI |
| New tool | module-level toolset builder + registration in the engine; must honor `resolve_workdir_file` containment |
| New checklist | `reference/checklists/*.md` (seeded into projects via `scaffold.py`) |
| Plugins | `plugins/` package hook points |

## 9. Verification & testing

- Engine tested at seams with scripted `FunctionModel` runs against temp
  workdirs (`tests/`, 767+ tests).
- Gates: `gates.bat` = `uv run pytest -q`, `uv run ruff check src tests`,
  `uv run mypy`; frontend: `npm run build` + vitest.
- Scenario evals: `codingdude eval` records/replays real sessions with
  attached checks.
- Standing quality loop: post-push review (Standards + Spec sub-agents;
  findings verified against code before fixing).

## 10. Operational notes

- Logs: `~/.codingdude/logs/server.log` (file handler attached by `serve`).
- Config loads per run — model/provider changes apply next run without a
  server restart; code changes need `codingdude restart`.
- The server reconciles stale `running` rows and orphaned processes at boot.
- Version pinning: backend version asserted by test; frontend version is
  baked at build — rebuild `frontend/dist` after frontend changes or version
  bumps.
