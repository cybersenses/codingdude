*Updated after commit 59ee09a (pushed). Main == origin/main, tree clean.*

## Current state
- **#73 FIXED and closed (`59ee09a`):** worker no longer exits 1 when the
  server bounces mid-run. Root cause was the unguarded `await sender_task`
  propagating `ConnectionClosedError` out of `run()` mid-engine-iteration.
  Fix: extracted `_sender_loop`/`_reader_loop` in `src/codingdude/worker.py`;
  on ws loss sender logs `WORKER_WS_LOST` and keeps draining the queue so the
  engine finishes and persists its own trace; worker exits 0 via the normal
  drain path. TDD: 10/10 worker tests (2 new). No reconnect logic (server was
  dead anyway) - deliberate.
- **#74/#75 repair round COMPLETE (earlier commits):** rail drag + persistence
  via `frontend/src/panes.ts` (single source for all four panes + dock);
  duplicate footer status removed (AgentStrip is sole indicator); CRLF in
  App.jsx restored; unused CodeMirror deps dropped. AgentStrip shows current
  activity; run output lives in the IDE dock.
- Full gates at close: 512 passed / 1 skipped, ruff + mypy clean; frontend
  vitest + build clean at the last UI commit.
- Server healthy on 127.0.0.1:8765.

## MUST DO after bounce
- Nothing mandatory. Clear to start fresh work.

## Open roadmap
- **R31 (run-end determinism residual)** - deliberately kept open as
  insurance: if the run-end hang / ghost-process / UI-settle family recurs,
  do NOT whack-a-mole - use existing instrumentation (worker-<session>.log,
  server.log, PROCESS_* trace events, process panel) and the
  diagnosing-bugs skill.
- **Known residual, unlogged ticket:** "run bounces its own server -> SSE
  severed, UI never sees completion" (from the `a4a33af` incident). Worker
  now survives it (#73) but the UI still misses RUN_FINISHED for that run.
- Trace writer has no locking - concurrent workers can interleave mid-write
  (BADLINEs at trace offsets 170333 / 200983 / 257002 in session ccb1b25c).
  Real but separate bug; not yet ticketed.
- Backlog: H7 streaming-vs-usage, orphan toolsets guard, `engine.run`
  decomposition, Trace/Sidebar/Standards polish, R1 vision half, delete
  stale `reference/` pydantic-ai copy.

## Known accepted gaps
- Post-push review loop is directive-driven, not a hard-enforced pipeline.
- Vision pixel gate has no live end-to-end check.
- Explorer rail width not user-resizable (deferred decision).

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
- ALWAYS leave handover notes (update this file) before ending a session.
- Keep ROADMAP.md statuses in sync when closing items; ticket tool closes
  record the closing commit.
