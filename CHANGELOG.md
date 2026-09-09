# Changelog

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
 — 2026-09-08

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
