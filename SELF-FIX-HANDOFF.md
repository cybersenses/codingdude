# CodingDude Self-Fix — Plan & Handoff Log

This document is the **plan and running log** for CodingDude fixing its own
source based on `cdissues.md`. It is written so that **another agent can take
over at any point** — every step records exactly what changed, how it was
verified, what the rollback point is, and what remains.

## How to use this document

- **If the fixing agent is still working:** read "Execution log" top-to-bottom.
  The last completed step is the current safe state.
- **If the fixing agent is broken / unresponsive:** go to
  "Recovery: if CodingDude is broken" below first.
- Every step ends with a **commit** and a **verification** line containing the
  exact command and its observed result. Trust only those lines.

---

## Goal

Fix the issues catalogued in `cdissues.md` (1 Critical, 9 High, 14 Medium,
13 Low), test-first where practical, committing after each verified step.

## Safety protocol (followed at every step)

1. **One finding per step.** Small, independently verifiable, independently
   revertible.
2. **Test-first:** write/extend a test that fails for the current bug, then fix.
3. **Verify per step:** run the targeted test file; at milestones run the whole
   gate: `uv run ruff check . && uv run mypy && uv run pytest -q`.
4. **Commit per step** with a message naming the finding id (e.g. `C1: …`).
   The commit SHA is the rollback point.
5. **Never leave the tree broken.** If a step's tests fail and can't be fixed
   quickly, `git checkout -- <files>` and log it as deferred.
6. **Beware self-reference:** some fixes touch `tools.py`/`ast_tools.py`/the
   harness the agent itself may use. After editing those, immediately smoke
   test file read/list and run the suite before committing.

## Environment facts

- Repo: `cybersenses/codingdude`, branch `main`.
- Toolchain: `uv run ruff check .`, `uv run mypy`, `uv run pytest -q`.
- `gh` CLI is **not** installed; GitHub ops use MCP tools + plain `git`.
- Baseline (before any fix): `main` @ `b049b29`; gate = ruff clean, mypy clean,
  131 passed (recorded in Step 0).

---

## Planned steps (ordered: Critical → High → Medium → Low)

| # | Finding | Summary | Files | Risk |
|---|---------|---------|-------|------|
| 1 | C1 | Persist session patterns via one `pattern_for()`; interpreters get exact-command patterns | `approvals.py`, `tools.py` | med (approval logic) |
| 2 | H1 | Attach git/coverage toolsets only when an ApprovalPolicy exists | `engine.py` | low |
| 3 | H2 | Worker forwards `fix_loop` to `engine.run` | `worker.py` | low |
| 4 | H3 | `run_coverage` uses argv (no `bash -c` injection); validate `source` | `tools.py` | med |
| 5 | H4 | `load_project_config` accepts documented `shell = "..."` shapes | `config.py` | low |
| 6 | H8 | `find_dead_code` becomes Workdir-contained | `deadcode.py`, shared helper | med (self-ref: file tools) |
| 7 | H5 | Resolve vision model; preserve real media type | `engine.py`, `worker.py`, `server.py`, `config.py` | med |
| 8 | H9 | String model override honoured | `engine.py` | low |
| 9 | H6 | Accumulate usage across sub-runs; budget checks between them | `engine.py`, `planning.py` | med |
| 10 | H7 | Non-streaming runs persist incrementally | `engine.py` | med |
| 11 | M1/M2 | `resolve()`/`glob` containment hardening | `tools.py` | med (self-ref) |
| 12 | M3 | `OUTSIDE_WORKDIR` case-insensitive + broader | `approvals.py` | low |
| 13 | M4/M5 | Token via env; `run_ws` respects `allow_testclient` | `server.py`, `worker.py` | med |
| 14 | M6 | `delete_session` cascades; `user_version` migrations | `db.py` | med |
| 15 | M7/M8 | MCP config never bricks a run; project can re-enable | `mcp_config.py` | low |
| 16 | M9 | Persist claim-verification retry | `engine.py` | low |
| 17 | M10 | Shared shell resolution (no hardcoded bash) | `tools.py`, `engine.py` | low |
| 18 | M11 | Attach the orphan toolsets | `engine.py` | med |
| 19 | M12/M13/L11 | Frontend revert index, dup skill fns, reload events | `frontend/src/App.jsx` | low |
| 20 | M14 | Use the TypeScript grammar for `.ts/.tsx` | `deadcode.py`, `repo_map.py`, `refactor.py` | low |
| 21 | L-list | Cleanups (cli no-op, dup return, empty-command guard, lazy INSTRUCTIONS, cosine, skills frontmatter, bench isolation, temp file) | various | low |

Steps may be merged if trivially related; each commit names the ids it closes.

---

## Recovery: if CodingDude is broken

1. **Find the last good commit.** See the "Execution log" — the last step whose
   verification line shows green is good.
2. **Inspect what a broken step changed:** `git log --oneline -n 5` then
   `git show <sha>`.
3. **Revert the offending step:**
   - whole step: `git revert --no-edit <sha>` (or `git reset --hard <prev-sha>`
     if nothing after it matters)
   - partial: `git checkout <prev-sha> -- <file>`
4. **Re-verify:** `uv run ruff check . && uv run mypy && uv run pytest -q`
   → expect "131 passed" (plus any tests added by completed steps).
5. **Resume** from the next un-finished step in the plan table.
6. If the harness itself (file tools / shell) fails to start, the source is
   likely mid-edit in `tools.py`/`ast_tools.py`/`approvals.py`; the fix is a
   `git checkout` of those files to the last green commit.

---

## Execution log

Each entry: **status**, files touched, the exact verification command + observed
result, commit SHA, rollback.

### Step 0 — baseline + docs  ✔
- **Commit:** `e63c85d` (config identity set first: `user.name=CodingDude`, `user.email=codingdude@local`).
- **Verification:** `uv run ruff check .` → *All checks passed*; `uv run mypy` → *no issues in 26 files*; `uv run pytest -q` → **131 passed**.
- **Rollback point:** `b049b29` (pre-doc).

### Step 1 — C1: pattern persistence (Critical)  ✔
- **Files:** `src/codingdude/approvals.py`, `src/codingdude/tools.py`,
  `tests/test_shell.py`, `tests/test_interactive_approvals.py`.
- **Change:** added `INTERPRETERS` + `MULTI_TOKEN_BINARIES`; rewrote
  `ApprovalPolicy.pattern_for()` (interpreters → exact command, multi-token
  families → two tokens); `_resolve_gate()` now persists
  `policy.pattern_for(command)` instead of `command.split()[0]`; `decide()`
  returns `NEEDS_GATE` for an empty command (was `IndexError`).
- **Red→green:** new tests failed first (`python -m pytest -q` persisted as
  `python`), then passed after the fix.
- **Verification:** `uv run pytest tests/test_shell.py tests/test_interactive_approvals.py tests/test_git.py -q`
  → **22 passed**; full `uv run pytest -q` → **135 passed**; ruff + mypy clean.
- **Commit:** `f0e371c`.
- **Rollback:** `git revert f0e371c` or `git reset --hard aad1ff0`.

<!-- END LOG -->
