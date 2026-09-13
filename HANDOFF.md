# Handoff note — to the next agent on duty

Left mid-session after a large autonomous push. If you're reading this, pick up
from here.

## State at handoff
- HEAD `61c1d05` + a new commit closing **R1 and R2** (see ROADMAP.md statuses).
  All gates ran green before commit: **192 tests passed, ruff clean, mypy clean
  (32 files), `npm run build` ok**.
- Roadmap now: R1 **done**, R2 **done**, R3 **done**, R4 **done**. Backlog
  section is empty — next work should open new `## R<n>` items.

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
