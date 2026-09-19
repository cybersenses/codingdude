# Handoff note - to the next agent on duty

*Updated after commit 0330dec (pushed). Main == origin/main, tree clean.*

## Current state
- **R35 (UI polish, VS Code-style) IN PROGRESS - ticket #72 Phase 1 done
  (`0330dec`, pushed):**
  - Center: FileExplorer (tree + Monaco tabs + diff) is the editor area.
  - Right: chat panel (prompt + messages) as aside, existing rightWidth
    divider.
  - Bottom: DockPanel is now a horizontal VS Code-style dock (tab strip on
    top + body) with drag-to-resize top edge; height persists in
    `cd-dock-h` (default 240, clamp 120-560). 'Files' removed from dock
    tabs (it is the center now). Footer stays status bar.
  - Fixed in passing: Processes tab crashed on bare `processes` identifier
    - now a proper prop (App already passed it).
  - User direction: do NOT aim to 100% copy VS Code - rearrange existing
    panels first, then highlight what makes us unique and what matters to
    the user.
  - **Next phase ideas:** narrow explorer gutter inside center; open Files
    tree default-expanded in center; panel tabs styling; unique-feature
    emphasis (agent status, run output, diff review).
- **R33 DONE** (`0cc5c28` prsum, `e445c05` post-push review directive,
  `404ca97` graph-informed reviews).
- **R34 done** (be12533 / afd0241 / a75b458) - Monaco file API/editor/diff.
- Frontend gates: vitest 16/16, build clean. Full backend gates last run:
  510 passed / 1 skipped, ruff + mypy clean (53 files).
- **Server needs a bounce to serve the new dist** (layout change not yet
  live-checked).

## MUST DO after bounce
- Bounce server; live-verify the new layout (center editor, chat right,
  dock bottom, dock resize + persistence).

## Open roadmap
- **R35 (UI polish) open - #72 in progress (Phase 1 done), #73 logged:**
  worker exited unexpectedly (code 1) without finishing the run. Belongs
  to the R31 hang family.
- R31 (run-end determinism residual) - **deliberately kept open** as
  insurance: if the run-end hang / ghost-process / UI-settle family
  recurs, do NOT whack-a-mole - use the existing instrumentation
  (worker-<session>.log, server.log, PROCESS_* trace events, process
  panel) and diagnose via the diagnosing-bugs skill.

## Known accepted gaps
- Post-push review loop is directive-driven (tool output guidance), not a
  hard-enforced pipeline - agent discipline may drift.
- Vision pixel gate still has no live end-to-end check.

## Environment notes
- Windows 11, project at G:/pydantic, venv ./.venv/Scripts/.
- Gates: ./.venv/Scripts/python.exe -m pytest -q; ruff check src tests;
  python -m mypy src; frontend: cd frontend && npx vitest run && npm run build.
- WSL git uses Windows GCM for credentials - push works from agent shell
  (git push origin main, ~seconds). Docker CLI: use docker.exe from WSL.
- tools.py and other files are CRLF - preserve; the edit tool keeps
  normalizing some files to LF, restore CRLF pre-commit when diff explodes.
- HANDOFF.md must stay UTF-8 (this file was once cp1252 and blocked edits).

## Process reminders
- TDD red-first at pre-agreed seams; full gates before any done claim.
- Every user message means continue-the-work; user says proceed/afk -> keep
  going without re-asking. Bounce = delivery mechanism, not a new task.
- Keep ROADMAP.md statuses in sync when closing items; ticket tool closes
  record the closing commit.
