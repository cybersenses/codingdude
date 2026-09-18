# Handoff note — to the next agent on duty

*Updated after commit 46957c3 (pushed). Main == origin/main, tree clean.*

## Current state
- **All roadmap items R1–R29 and all tickets closed.** Backlog empty.
- Gates at last run: **475 passed / 1 skipped**, ruff clean, mypy clean (52 files), vitest 4/4, frontend build ok.

## Just shipped (46957c3) — post-run hang + reattach storm fix
Symptom: after RUN_FINISHED the UI never settled until the user hit stop; a
shell process (codegraph node) lingered.
- **Server** (worker.py): _finish_run() now drains the post-run tail
  (engine.drain_post_run(), bounded 150s) **before** emitting the terminal
  event. Previously the tail was cancelled ~2s after RUN_FINISHED at worker
  teardown -> MEMORY_EXTRACTED never emitted, and a tail mid-LLM-call could
  hang asyncio.run cancellation -> worker (and its MCP children) stayed alive.
- **Frontend** (App.jsx): attachedRunRef is now written in attach() and
  cleared on every exit path (terminal, SSE give-up, worker-gone, stop()).
  The ref was never assigned before, so the boot-reattach effect re-fired on
  every 5s activeRuns poll, stacking duplicate EventSources that competed
  for the channel single-consumer queue.

## Verify next live run (user watching)
- Trace should show MEMORY_EXTRACTED **before** RUN_FINISHED.
- UI settles to finished; no lingering processes after run end.

## Known accepted gaps (do not fix by surprise)
- RunChannel SSE queue is single-consumer; competing consumers steal events
  (no broadcast). Multi-consumer broadcast is a possible follow-up if it bites.
- No live end-to-end verification of the vision pixel gate (needs configured
  models.vision).

## Environment notes
- Windows 11, project at G:/pydantic, venv ./.venv/Scripts/.
- Gates: ./.venv/Scripts/python.exe -m pytest -q; ruff check src tests;
  python -m mypy src; frontend: cd frontend && npx vitest run && npm run build.
- WSL git now uses Windows GCM for credentials — push works from agent shell
  (git push origin main, ~seconds). Docker CLI: use docker.exe from WSL.
- tools.py and other files are CRLF — preserve; the edit tool keeps
  normalizing some files to LF, restore CRLF pre-commit when diff explodes.

## Process reminders
- TDD red-first at pre-agreed seams; full gates before any done claim.
- Every user message means continue-the-work; user says proceed/afk -> keep
  going without re-asking. Bounce = delivery mechanism, not a new task.
- Keep ROADMAP.md statuses in sync when closing items; ticket tool closes
  record the closing commit.
