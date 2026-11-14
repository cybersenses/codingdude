# Changelog

## Unreleased

### Added

- **Delegation spends the session's budget (R93-A)**: a delegated run is handed
  the parent's usage accumulator, so its requests and tokens count against the
  run that caused them instead of vanishing. Its cap is the delegation slice
  (`used + [delegation].max_requests`, bounded by the session limit) rather than
  a fresh allowance per delegation. The operator kill switch is now observed at
  every tool boundary *inside* a delegation, not only between the parent's calls.
- **Tool output bounded at the source (R93-B)**: an oversized tool return is
  truncated where it is produced (80k chars → 40k head/tail) instead of arriving
  whole. Our own tools already self-cap; this bounds what MCP servers send.
  Cache-bust reporting from the provider's own numbers comes with it.
- **Local-OTLP tracing (R93-C)**: new `[telemetry]` table (`enabled`,
  `otlp_endpoint`, `service_name`). Traces go to a local collector only —
  `send_to_logfire=False`, no token, nothing off the machine — and every agent
  carries a name, so a failed run names the agent and request instead of
  requiring inference. Off by default; a missing collector never fails a run.
- **Pre-push review gate (R92)**: `git_push` refuses unless a recorded two-axis  review covers the exact diff being published. The record is content-addressed
  (`sha256` of the committed range plus the working tree), so amending or
  rebasing without changing the diff keeps it valid and fixing a finding voids
  it. `git push` through the shell is refused for the same reason, and the file
  tools refuse to touch the git directory, so a record cannot be fabricated by
  writing it. Post-push review stays as a failsafe.
- **Per-request context compaction (R91)**: a mechanical, LLM-free guard runs
  before every model request and compacts when the token estimate crosses the
  window threshold, instead of only at run start. A run can no longer grow until
  the provider rejects it with a context-length 400; the guard is fail-open, so
  a guard error degrades to sending the request rather than killing the run.
- **Prompt caching for every agent (R91)**: one resolution point turns config
  into pydantic-ai capabilities for the main loop, the fix-loop retry and the
  claims retry (conversation + retention) and for the one-shot agents
  (retention only). New `[models]` keys `prompt_cache`,
  `prompt_cache_messages`, `prompt_cache_settings`; unknown passthrough keys
  fail at load instead of being silently dropped.
- **Long runs (R80)**: `--long-run assisted|unattended` adds the sandbox lane,
  durable resume, structured evidence gate, evaluator loop, operator files, and
  a publish cycle that only ever pushes `codingdude/longrun-*` branches with
  draft PRs. Timeout auto-resume and lane bootstrap included.
- **Planning depth**: PRDs, technical designs, roadmap items and tickets with
  per-step evidence; function-tagged plan steps that phase-switch the session
  (`[models.functions.<name>]`); `delegate` sessions staffed by cognitive
  function with a registry-locked tool policy.
- **Wireframes (R85)**: screen-design packs, a flow map, inline DSL editing and
  implement handoff, rendered by the wireloom grammar.
- **Model tooling (R81/R86)**: per-run model picker in the composer, live model
  list fetch for OpenAI-compatible providers, custom `[providers.*]` tables.
- **Editor reveal (R69)**: `reveal_code` opens a file in the editor at the cited
  lines; chat citations are clickable.
- **Kickoff prompts (R71)**: every session's first turn rides an executed
  orientation block, overridable per project with `[kickoff]`.

### Changed

- pydantic-ai 2.66 → 2.68 and `pydantic-ai-harness` 0.68 added (R93-B). The
  harness pins the core version exactly, so this is one move. Note for anyone
  with a live server: the venv moves on the next `uv sync`.
- `main` is protected and changes land through PRs with CI (R73/R74); issue and
  PR templates plus a Contributor Covenant code of conduct are in the repo.
- `github-mcp-server.exe` is no longer vendored; `setup-codingdude.bat` fetches
  the upstream release (R74).
- The user manual is split into pages under `docs/manual/` (R70).
- Trace deltas are coalesced by default with a full-detail toggle (R79).
- Usage is tagged by cognitive function, so the Cost panel breaks spend down by
  function as well as by model.

### Fixed

- Delegated spend was counted twice: a delegation's requests and tokens sat in
  both its own usage row and the run's row (the shared accumulator made both
  true at once), so the session total — and the Budget Cap that reads it —
  double-counted every delegation and would halt at roughly half the real
  spend. The two rows now partition the spend, and checkpoints order by a
  per-session sequence rather than a filesystem timestamp (`st_ctime` is
  inode-change time on POSIX, and capturing into an older checkpoint bumps it).
- A malformed `[telemetry] enabled` value (quoted `"false"`) no longer stops a
  worker at boot; like a malformed endpoint it logs once and leaves tracing off.
  A missing `pydantic-ai-harness` degrades to the history guard instead of
  failing every agent build.
- Provider context-length 400 that killed runs mid-session (the per-request
  guard above); the claims retry was the last path that could still overshoot.
- Artifacts panel crash on SSE deltas after a card was replaced (R87).
- `ask_user` payloads are validated at the tool boundary and the UI card can no
  longer take down the workspace; a malformed payload gets a readable
  `ModelRetry` instead of a React error (R90).
- Reviewer sub-agent now runs with repository tools and a prompt it can act on;
  it used to answer without file access (R90).
- `show:` panel deep-links no longer bury the editor in a merged dock group
  (R89).
- Run-failure visibility: worker stderr is captured and surfaced, MCP pre-flight
  blocks a run that cannot reach its servers, and `repo_map`/`arch_lint` were
  moved off the critical path (R76/R77).
- Navigation no longer grows the page (it scrolls internally), floating groups
  are clamped on screen, and the dock no longer produces a phantom scrollbar
  (R67/R88).

### Security

- Dependency advisories cleared across Python and npm trees; doMPurify pinned
  (R66).
- Constant-time token comparisons on the auth seams; mermaid renders with
  `securityLevel: 'strict'`; `gh` calls resolve through `shutil.which` with an
  argv list, no shell (R66).
- Security gate (Bandit + Semgrep + secret regexes) fails closed on a finding.

## 0.4.0 — 2026-09-21

Analysis hardening (R47) + codebase hygiene sweep.

### Added
- Security gate (#155): Bandit + secret regexes + bundled Semgrep rules, ModelRetry, fails closed
- Mutation testing trustreport (#156): mutmut-backed survived-mutant evidence
- On-demand cProfile (`profile_code` tool, #158) and A/B micro-bench (`compare_bench`, #160)
- Hypothesis API fuzzing (`fuzz_api` tool, #159)
- `resolve_workdir_file`: shared containment-checked file resolution for the analysis tools
- `setup-codingdude.bat`: one-shot setup that installs everything (uv, deps, Semgrep CLI, frontend build)

### Changed
- Contract docstrings on all public store/engine/server symbols (arch-lint clean)
- `utc_now_iso` is the single canonical timestamp helper (was duplicated in 6 modules)
- Dead `next_target`/`body_tail` parameters removed from the CFG builder

### Fixed
- UI version badge showed 0.3.0 after the bump: the frontend bakes `__APP_VERSION__ = package.json version` into the bundle at build time (vite `define`). Release rule: after bumping the version, run `npm run build` and ship the rebuilt `frontend/dist/` — a stale bundle keeps reporting the old version. Backend `__version__` is now derived from installed package metadata, pinned by `tests/test_version.py` (single source: pyproject.toml)

## 0.3.0 — 2026-09-09

Modernization completion (WS-C/E/F/G/H remainder).

### Added
- Trace viewer tab: replay every traced event of a session (gates, terminals, tool calls)
- `run_coverage` agent tool: pytest-cov execution with per-file missing-line report
- `find_unused_exports` agent tool: knip integration for JS/TS projects (uses project devDependencies, never auto-installs)
- `find_dead_code` agent tool: vulture (Python) + tree-sitter (JS/TS) unused-symbol detection
- On-demand code review: Diff-tab "Run review" button → reviewer findings
- Design tokens: brand palette defined as Tailwind @theme aliases
- Typed API layer (`api.ts`) with generated-style event/response models — first step of the TS migration
- Memory extraction wired into the worker (cheap-model post-session fact banking)
- Binary gates/terminals now land in the JSONL trace

### Changed
- `emerald-*` accent classes swept to `brand-*` tokens

### Fixed
- review refactor shared between plan-completion and on-demand flows

## 0.2.0 — 2026-09-08

Uber-agent layer (tickets 18–22) + modernization pass (WS-A–H).

### Added
- Directives: `~/.codingdude/DIRECTIVES.md` injected into every run (project AGENT.md as second layer), budget-capped, gate-protected edits
- Skills: SKILL.md registry (global + project), progressive disclosure via `load_skill`, seed skills (tdd, code-review, debugging)
- Planning mode: `propose_plan` → approval card → tracked steps (`update_step`) → automatic review pass with findings fed back to the model
- MCP client: global + per-project `mcp.json` merge, disable/enable, MCP tab in the UI
- Semantic search: injectable embedder, hash-cached file index, `semantic_search` tool, similarity-ranked memory
- Budget Cap: per-session spend limit, hard stop, survives `--yolo` (exit 3)
- Observability: per-session JSONL run traces; versioned prompt files (`prompts/*.md`)
- Web: login flow (HttpOnly session cookie, stable password in `~/.codingdude/server-token`), plan/review/findings cards, live Diff/Files/Cost/Memory/MCP panels

### Changed
- Shell/git subprocesses are now async and run with scrubbed environments (no secret env vars)
- Terminal panel delegates to the tool timeline; grep enforces per-file size caps

### Fixed
- Approval-card freeze (TOOL_CALL_START raced GATE_REQUEST and cleared the card)
- Stop leaking worker processes when the browser's event stream dropped
- /api prefix 405 when FastAPI serves the built frontend
- Empty sessions left behind by failed runs

### Engineering
- CI workflow (ruff + mypy + pytest + scripted bench), ruff lint clean, error taxonomy (`errors.py`), structured logging, gold-task benchmark (`bench.py`, `--live` for real models)
