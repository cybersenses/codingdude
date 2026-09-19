*Updated after commit 1e2aeb8 (pushed). Main == origin/main, tree clean.*

## Current state
- **R35 (UI polish, VS Code-style) IN PROGRESS - ticket #72, Phases 1-3
  done, pushed:**
  - Phase 1 (`0330dec`): center = FileExplorer/editor, right = chat aside,
    bottom = horizontal dock (drag-resize, height in `cd-dock-h`), 'Files'
    dock tab removed. Fixed Processes-tab bare `processes` crash.
  - Phase 2 (`7e653ef`): chat prompt rearranged - textarea full-width,
    Send button top row; all options (attach, image chip, suggest,
    fix-until-green, model, yolo, notify) moved to a bottom row.
  - Phase 3 (`1e2aeb8`): file tree moved to its own left rail (`w-52`,
    refreshes every 10s + on mount); Monaco editor takes the full main
    area (tab strip + save/reload/diff toolbar + editor). Workspace state
    lifted into `useFileWorkspace(sessionId)` hook in App.jsx so tree and
    editor share tabs/draft/dirty/diff. No persistence/resizable width on
    the rail (accepted for now).
  - User direction: do NOT 100% copy VS Code - rearrange panels first,
    then highlight what makes us unique / matters to users (agent status,
    run output, diff review).
  - **Next phase ideas:** emphasize unique features in the layout; dock
    styling; explorer rail polish (resize/drag-drop open); live-verify
    layout end to end.
- **R33 DONE** (`0cc5c28` prsum, `e445c05` post-push review directive,
  `404ca97` graph-informed reviews).
- **R34 done** (be12533 / afd0241 / a75b458) - Monaco file API/editor/diff.
- Frontend gates: vitest 16/16, build clean. Full backend gates last run:
  510 passed / 1 skipped, ruff + mypy clean (53 files).
- **Live-verified after bounce (8765 serves current dist):** Phase 2/3
  layout confirmed working by user + served-bundle check.

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
