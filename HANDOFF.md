# Handoff note — to the next agent on duty

Left after planning R5–R11 end-to-end. If you're reading this, pick up from here.

## State at handoff
- HEAD `78ed9a4` (pushed): R1–R4 **done**; **R7-thin tracer DONE** (ticket #3
  closed): `codingdude.evals` (export/replay/checks/run_scenarios) +
  `tests/scenarios/*.json` incl. deliberately-failing broken-skill. 200 tests,
  ruff, mypy green. Thickening (real-session recording, curated scenarios, CI)
  still open on R7. Next: **R5-tracer** (ticket #1) — worktree+venv tier 1,
  no Docker needed.
- `docs/PLANS-R5-R11.md` = the ratified plan per item (designs, tracer-bullet
  cuts, explicitly-not-building list). Design decisions #2–#3 record the
  postures; tickets #1–#7 each carry their plan summary in the body.
- **Execution order (ratified):** R7-thin → R5-tracer → R11-tracer →
  R6-tracer → R9 → R8 → R10 — one thin vertical slice per item per session;
  thickening passes get new tickets once each tracer bullet closes.
- User is installing Docker Desktop and adding the Docker MCP server (for
  ad-hoc use only — R5's lifecycle is native `sandbox.py`, not MCP-driven).

## Next action
Start R5-tracer (ticket #1): `sandbox.py` tier 1 — git worktree + ephemeral venv,
create/exec/teardown tools, byte-identical teardown guarantee.

## What was just shipped
- **R2 (hang):** real culprit was `es.onerror` in `frontend/src/App.jsx` — it
  used to close the SSE and silently pretend the run finished. Now:
  reattach-with-backoff while `/runs/{id}/alive` says the worker lives, honest
  error after 5 failed attempts, clean finish + message reload when the worker
  is already gone. Plus a client watchdog: `quietSeconds >= 30` shows
  "still working… (no output for Ns)" in the footer.
- **R1 (vision):** `src/codingdude/vision.py` — `inspect_image(path, question)`
  tool, wired via `PluginContext.vision_model` (only when `models.vision` is
  configured). Shell capture hook in `build_shell_toolset(on_render=...)` emits
  `RENDER_CAPTURED` for fresh image files after each command. Renders tab now
  pairs `*-dark/*-light` and `*-before/*-after` side-by-side.

## Deliberately NOT done (don't "fix" by surprise)
- **No end-to-end visual verification was run**: the vision toolset is unit-
  tested with `TestModel`, but nobody has yet watched the UI reattach during a
  real dropped connection, or watched the agent close a real pixel gate via
  `inspect_image`. Both are worth a live sanity pass with a real vision model.
- Rendering pairing is name-convention based (`-dark`, `-before`, …); if skills
  produce different naming, extend the `PAIRS` regex in the Renders tab.
- `models.vision` unset → no `inspect_image` tool at all (by design); the agent
  silently can't judge pixels in that config. Consider a trace hint if that
  bites.
- Open thread from memory: the user never confirmed memory/compaction behaved
  after the request_limit change — follow up if they report it again.
- R1's "renders persisted with the session" is still satisfied indirectly (the
  workdir scan); nothing is copied into the DB. If renders must survive the
  workdir moving/deleting, that's new work.

## House rules reminders
- Every user message means "continue the work" — bounce with
  `python -m codingdude.restart` only as delivery, not as the task.
- Workdir-scoped planning data lives via the planning agent tools; keep
  ROADMAP.md statuses in sync when you close items.
