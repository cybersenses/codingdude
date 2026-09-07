# 01: Foundations & rename

**What to build:** The prefactor that makes everything else easy. CodingDude exists as a project: the placeholder prototype is deleted, the package/CLI is named `codingdude`, the repo is git-initialized, and the user config directory holds the model lineup (main `deepseek-v4-pro`, Subagents `deepseek-v4-flash`, failover `glm-5.3` via FallbackModel) and shell setting (Git Bash default). The SQLite schema for sessions, messages, approvals, Memory, and usage exists, and the FunctionModel test harness with temp-Workdir fixtures proves itself green by running one trivial scripted run end-to-end and finding it persisted.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] `codingdude` installs and runs as the CLI name; the old prototype code is gone
- [x] Repo is a git repository with an initial commit
- [x] First run creates the config directory and SQLite database without manual steps
- [x] Engine-seam harness (FunctionModel + temp Workdir fixtures) runs a scripted turn and the messages appear in the database
- [x] A scripted run against a dead primary model transparently failsover to the fallback model

## Comments

2026-09-07: Implemented in commit b4950f7. 11 tests green (engine seam, config, db, failover, cli), mypy clean. `CODEDUDE_HOME` env var added for test isolation. Model resolution is lazy (providers require API keys at construction), so the engine takes an injectable model for tests and builds FallbackModel from config in production.
