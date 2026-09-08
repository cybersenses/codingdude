# Changelog

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
