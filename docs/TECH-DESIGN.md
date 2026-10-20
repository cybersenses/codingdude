# CodingDude — Technical Design Document

**Status:** living document · **Hierarchy:** [PRD.md](PRD.md) (why/what) → **this doc** (how, system-level) → [adr/](adr/) (specific decisions) → [specs/](specs/) (per-feature) → [ROADMAP.md](../ROADMAP.md) (execution)

Vocabulary follows [CONTEXT.md](../CONTEXT.md). This document describes the
system as built; each claim cites the code that implements it. ADRs record
*why* the load-bearing choices were made — this doc records *what exists*.

---

## 1. System overview

```
 Browser (React/Vite SPA)
    │ SSE (events) + HTTP JSON (auth, config, sessions)
    ▼
 Server (server.py, asyncio HTTP) ── SQLite store (db.py)
    │ spawns per-run, bridges WebSocket ⇄ SSE
    ▼
 Worker subprocess (worker.py) ── Engine (engine.py, pydantic-ai)
    │ tool calls (Workdir-contained)          │
    ▼                                          ▼
 Filesystem / shell / git / gh / MCP      LLM providers (user-configured)

 Headless Run (cli.py `run`) — engine in-process, no server
```

Three processes matter: **server** (UI, persistence, session auth), **worker**
(one subprocess per run; dies with its run), **engine** (pydantic-ai agent
loop, shared by worker and headless).

## 2. Components

| Component | File(s) | Responsibility |
|---|---|---|
| Engine | `src/codingdude/engine.py` | Agent loop, model lineup resolution (`_model_from_name`), toolset construction, approvals, budget enforcement, failover |
| Server | `src/codingdude/server.py` | HTTP+SSE, login (`/auth/local` browser attestation, bearer for local clients), run lifecycle endpoints, config API, static dist serving |
| Worker | `src/codingdude/worker.py` | Per-run subprocess; connects back over WebSocket; applies project `[models]` overrides; streams trace events; memory extraction tail |
| Store | `src/codingdude/store.py` | SQLite persistence: sessions, messages, traces (JSONL), memory entries, tickets/roadmap, artifacts |
| Config | `src/codingdude/config.py` | `~/.codingdude/config.toml` (`CODEDUDE_HOME` override): model lineup, user-defined `ProviderDef` providers, shell, per-project `[models]` overlay (`apply_project_models`) |
| Tools | `src/codingdude/tools.py`, `analysis.py`, `planning.py`, `delegation.py`, `research.py`, `vision.py`, … | All agent tools; file ops are Workdir-contained; analysis tools (AST/CFG/coverage/mutation/benchmark/fuzz) resolve paths via `resolve_workdir_file` |
| Codegraph | `src/codingdude/codegraph_boot.py` + codegraph MCP | Tree-sitter symbol index per project; navigation via explicit `projectPath` |
| Skills/directives | `~/.codingdude/skills/`, `DIRECTIVES.md` | Progressive-disclosure procedures (`load_skill`), always-injected user rules |
| Memory | `memory.py` (MemoryStore) + engine | Keyword+semantic retrieval, RAG summaries; solutions (`record_solution`) referenced at session start |
| Frontend | `frontend/src/` (React/Vite/Tailwind, `api.ts` typed layer) | Chat, Approval/plan/artifact cards, Diff/Files/Trace/Renders/Memory/MCP/Config tabs, Monaco editor, run composer with provider-aware model selector |

## 3. Run lifecycle (web)

1. Browser `POST /run` (session, workdir, optional `provider:model` main).
2. Server spawns worker subprocess; worker dials back over local WebSocket.
3. Worker builds config (`load_config` + `apply_project_models`), constructs
   engine (approvals relayed to UI as cards), runs the agent loop.
4. Every event (tool calls, gates, approvals, terminals) streams server → SSE →
   browser and persists to SQLite + JSONL trace.
5. Run end: deterministic finish, post-run memory extraction tail (R30/R31),
   worker exits with its run — kill/cancel is process death (ADR-0002).
6. Crash/reopen: frontend reconnect-resumes live run from persisted history (R29).

**Headless** runs the same engine in-process with a fail-safe gate policy
(ADR-0003): gated action aborts with exit 2 unless `--yolo`; budget stop exits 3.

## 4. Model resolution & providers

Single seam: `engine._model_from_name(name, base_url, providers)`:

1. `provider:model` prefix matches a user `ProviderDef` with `base_url` →
   `OpenAIChatModel` on `AsyncOpenAI(base_url, key)` — any OpenAI-compatible API.
2. `zai:` + configured `fallback_base_url` → dedicated coding-plan endpoint.
3. else pydantic-ai `infer_model` (native providers).

Key resolution `provider_effective_key`: env var (`env_var`, legacy name, or
`<NAME>_API_KEY`) wins over stored `api_key`. Slots: main, subagent, fallback,
review, vision, extraction. Secrets never leave: GET returns presence/mask,
PUT uses the SECRET_MASK sentinel. Config loads per run — changes apply from
the next run, no server bounce.

## 5. Trust architecture

- **Tiered approvals** (interactive cards; pattern approval session-scoped;
  always-gated: push/PR/release/destructive fs — see ADR-0004).
- **Budget cap** hard-stops regardless of `--yolo`.
- **Environment scrubbing** of KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL vars in all
  subprocesses; server binds loopback with browser-attested local auth.
- **Security gate** (Bandit + Semgrep + secret regexes) fails closed.

## 6. Data & persistence

- SQLite under `CODEDUDE_HOME` (default `~/.codingdude`): sessions, messages,
  memory, roadmap/tickets, artifacts. JSONL trace per session (gates,
  terminals, tool calls, RENDER/IMAGE events).
- Per-project: `.codegraph/` index, `AGENT.md`, project skills, `mcp.json`,
  optional `[models]` overrides.
- Versioning: backend version = package metadata (pinned by test); frontend
  bakes `__APP_VERSION__` at build — rebuild dist after bumps.

## 7. Extension points

- **Providers** — config-only; no code change for any OpenAI-compatible API.
- **MCP** — global + project `mcp.json` merged; per-server enable/disable.
- **Skills** — drop a `SKILL.md` directory (global or project); loaded by name
  with progressive disclosure.
- **Tools** — new analysis tools follow the `resolve_workdir_file` containment
  contract; register in the engine toolset.

## 8. Testing & verification

Engine tested at seams with scripted `FunctionModel` runs against temp
Workdirs (`tests/`); frontend vitest + `npm run build`; gates: pytest, ruff,
mypy (see `gates.bat`). Post-push review flow (Standards + Spec sub-agents,
findings verified against code) is the standing quality loop.

## 9. Known limits / deferred

From ADR-0004: shell tier check is heuristic (not a sandbox); approved commands
run with full user permissions; web fetch permits localhost probing. Deferred:
Job Object/container isolation, PyInstaller packaging, per-command env
allowlists.
