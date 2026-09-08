# Proposal: CodingDude modernization — full-stack review against 2026 standards

Status: draft for discussion

## 1. Where we are (audit summary)

CodingDude is feature-rich (all 17+5 tickets) but its *engineering substrate* lags its features. Key gaps from the audit, prioritized for a single-user local tool:

**HIGH impact**
- No CI pipeline (tests+mypy exist but nothing runs them on change)
- Blocking I/O in async paths: sync `subprocess.run` inside async tools, sync sqlite3 in the engine — the event loop stalls during every shell command
- No observability: pydantic-ai ships OTel instrumentation; we emit zero traces
- Evals: 2 gold tasks, both scripted — can't detect prompt/model regressions
- Shell "sandbox" is regex heuristics; subprocess inherits the full user environment; `shell=True` in gh tools; web tools allow localhost URLs (SSRF into local services)
- Frontend is untyped JS, one 537-line App.jsx, no error boundary

**MEDIUM**
- `Engine.run` god-method (~170 lines, 9 inline imports — layering-by-need, not design)
- Config scattered across 3 systems, unvalidated, and mutates `os.environ` at load
- No error taxonomy (`GateRequired` in tools.py, one exception elsewhere), `print()` instead of logging, token printed to stdout
- Grep tool reads whole files unbounded; `resolve()` misses symlink escapes
- Prompts hardcoded as string literals (can't version or eval them)

## 2. What "modern" looks like (2026 landscape)

**Agent engineering** — observability is table stakes, evals are the maturity frontier: ~89% of teams have observability, only ~52% run evals. The standard primitive set is **Runs → Traces → Threads**: every run traced step-by-step (model call, tool call, latency, tokens), continuously evaluated. pydantic-ai hands us this via its `Instrumentation` capability — we just never turned it on.

**Human development pipeline** — the traditional loop (design → prototype → measure → ship) maps directly onto agent + UI work:
- **Prototyping**: new UI ideas get a throwaway build behind a flag before touching main components
- **UI design**: design tokens (colors/spacing/type) as a single theme source, not Tailwind classes scattered per component
- **A/B testing**: at single-user scale this means **variant testing** — e.g. two prompt strategies or two model configs measured against the gold-task bench, and UI experiments behind flags. The standard practice (flags + measurable hypothesis + flag cleanup) applies directly
- **Progressive delivery**: features ship dark behind config flags (`[features] planning=true`) and flip on when proven

## 3. Proposed workstreams

### WS-A — Engineering hygiene (foundation, do first)
1. CI pipeline: GitHub Actions (or local `act`/pre-push hook) running `ruff check`, `mypy`, `pytest`, `python bench.py` on every commit
2. `[tool.ruff]` (lint+format) — one-time cleanup commit, then enforced
3. `errors.py` taxonomy: `CodingDudeError` base; move `GateRequired`; add ConfigError
4. `logging` module with structured formatter; replace every `print()`; token goes to the token file only, never stdout
5. Config: one pydantic-settings `Settings` model (app+shell+models+providers+features), validation with clear errors, no env mutation

### WS-B — Async correctness
1. Shell/git/gh tools → `asyncio.create_subprocess_exec`
2. SQLite → keep sqlite3 but move all calls to `anyio.to_thread` (cheaper than aiosqlite migration), or aiosqlite if friction appears
3. Grep: size cap per file + total; `resolve()` gains a symlink-realpath check
4. Typing: strict-ish mypy, `Protocol`s for Embedder/ask-callback/policy

### WS-C — Observability & prompt management
1. Enable pydantic-ai `Instrumentation` capability → OTel traces per run (spans: model request, each tool call); local OTLP endpoint optional, default JSONL trace file per session
2. Trace viewer: minimal UI tab replaying a run's spans next to the chat timeline
3. Prompts → versioned files (`src/codingdude/prompts/*.md`) loaded at startup; the bench references them so prompt changes are measurable

### WS-D — Evals to the frontier
1. Grow bench to ~15 scripted gold tasks covering every skill (edit, test loop, review findings, plan adherence, directive compliance)
2. Scoring: pass/fail + tokens + latency per task; history table so changes trend
3. Live mode stays manual/gated; a `bench --live --suite regression` runs pre-release

### WS-E — Security hardening + threat-model ADR
1. Shell: deny-by-default binary allowlist (configurable), env scrubbing (strip secrets vars from subprocess env)
2. Drop `shell=True`; SSRF: keep localhost fetch behind an explicit config flag, default off
3. ADR: threat model — what the approval tiers actually defend against, and what they don't (documented limit: no true OS sandbox; document Windows Job Object option as future)

### WS-F — Frontend modernization
1. TypeScript migration (Vite makes this incremental: rename + strict tsconfig, typed event/API models shared with backend via generated types from FastAPI's OpenAPI)
2. Split App.jsx into components + a small store (zustand) for run/session state; ErrorBoundary at the app root; stable list keys
3. SSE hook with automatic reconnect + backoff (events survive transient drops)

### WS-G — UI/UX pipeline (the human loop)
1. Design tokens: Tailwind theme file = single source (emerald/neutral palette, spacing, type scale); all components consume tokens
2. Prototyping flow: new screens get a prototype route behind a feature flag, user feedback, then merge — never straight to the main UI
3. Variant testing: config flags (`[features]`) + the bench for prompt/model A/Bs; every experiment needs a hypothesis and a removal date (anti flag-sprawl)
4. Human review pipeline: PR-style review of UI changes via screenshots (the browser-use tooling can snapshot before/after)

### WS-H — Release hygiene
Version bumps + CHANGELOG.md per feature batch; `uv build` produces an artifact; git tags per release.

## 4. Sequencing

1. **WS-A** (hygiene unlocks safe change)
2. **WS-B** (correctness under load)
3. **WS-C + WS-D** (see what the agent is doing; measure changes) — the highest-leverage pair
4. **WS-E** (security hardening with real threats documented)
5. **WS-F + WS-G** (frontend quality + the human design loop)
6. **WS-H** throughout (version + changelog per workstream)

Roughly 6–8 focused sessions. Each workstream lands independently and nothing blocks daily use.
