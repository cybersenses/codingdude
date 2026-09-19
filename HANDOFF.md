*Updated after commit e13e0ac (pushed). Main == origin/main, tree clean.*

## Current state
- **R31 CLOSED (`e13e0ac`):** run-end state is now durable. New `runs` DB
  table (run_id, session, worker pid, status, exit_code, timestamps);
  server records start at spawn, worker records terminal status in
  `_finish_run`. Every trace event is stamped with `run_id` (engine tracer),
  so events are attributable across bounces forever. Server boot reconciles
  orphaned 'running' rows to 'interrupted' (idempotent). Also removed an
  accidentally duplicated `runner()` def in `worker.run`. Gates: 523 passed
  / 1 skipped; ruff + mypy clean. New tests: test_db.py runs lifecycle,
  test_run_trace.py (run_id stamping), test_server.py boot reconcile.
  Note: server.py was normalized to consistent CRLF (33 pre-existing LF-only
  lines cleaned in passing).
- **#78 FIXED and closed (`862a540`):** run that bounces its own server no
  longer leaves the UI hung/errored. SSE reconnect budget raised from
  5 attempts (~15s) to 30 attempts (~2min, linear backoff capped at 5s);
  helpers `sseRetryDelayMs`/`SSE_MAX_RETRIES` live in `frontend/src/reattach.ts`.
  Give-up path now reloads persisted messages before declaring error.
- **#79 FIXED and closed (`1e5fb7b`):** trace BADLINEs gone. New
  `src/codingdude/traces.py::append_trace_line` — one `os.write` per line
  under `O_APPEND` + in-process lock; engine tracer and worker
  `trace_terminal` both migrated. Threaded stress test proves zero malformed
  lines.
- Full gates at close: 515 passed / 1 skipped, ruff + mypy clean; frontend
  vitest 24/24 + eslint + vite build clean.
- **#73 FIXED and closed (`59ee09a`):** worker no longer exits 1 when the
  server bounces mid-run. Root cause was the unguarded `await sender_task`
  propagating `ConnectionClosedError` out of `run()` mid-engine-iteration.
  Fix: extracted `_sender_loop`/`_reader_loop` in `src/codingdude/worker.py`;
  on ws loss sender logs `WORKER_WS_LOST` and keeps draining the queue so the
  engine finishes and persists its own trace; worker exits 0 via the normal
  drain path. TDD: 10/10 worker tests (2 new). No reconnect logic (server was
  dead anyway) - deliberate.
- **#75/#77 COMPLETE (`ffe2fbc`):** run output view in the dock — new
  `GET /sessions/{sid}/runs` (R31 runs table, newest first) + Output tab
  (run selector w/ status badges, selected run's trace events grouped by
  run_id; pre-R31 events under '(unattributed)'). Gates: 525/1, ruff+mypy,
  eslint, 29/29 vitest, build ✓.
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
- All roadmap items R1–R35 done. Remaining is the backlog: H7
  streaming-vs-usage, orphan toolsets guard, `engine.run` decomposition,
  Trace/Sidebar/Standards polish, R1 vision half, delete stale
  `reference/` pydantic-ai copy, R35 leftovers #75/#77 (run output in IDE
  shell).

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

## Handover 2025-09-19 (e082906)
- Orphan-toolsets guard shipped: `rename_symbol` + `worktree_create` now gate
  through the approval policy (deny → ModelRetry, headless → GateRequired) and
  `rename_symbol` emits `EDIT_APPLIED kind:'rename'` per modified file
  (trace/checkpoints/UI see mass renames). `build_refactor_toolset(workdir,
  approvals, on_edit)`; wired via `ctx.on_edit` in plugins `build_all`.
- Backlog item "vendored reference/ deletion" done earlier this session
  (259MB freed); `ReferenceStore._prune_deleted()` keeps the index honest.
- Gates: 531 passed/1 skipped; ruff + mypy clean; pushed, tree clean.
- Remaining backlog: `engine.run` decomposition, H7 streaming-vs-usage,
  R1 vision half.
