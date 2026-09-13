# Handoff note — to the next agent on duty

Left with the **entire R1–R11 roadmap closed**: every item has a shipped tracer
and (R5–R10) a thickening pass. Backlog is empty — next session brainstorms the
next wave.

## State at handoff
- HEAD (this commit): R1–R11 all done. 261 pytest, ruff, mypy (39 files),
  npm build green. All pushed.
- **Deliberately deferred as information-thin (not debt):**
  R7 curated eval scenario *library* (content, not mechanism);
  R8 contract-first codegen (needs a codegen design).
- **Standing deliberately-open verification gaps (do not "fix" by surprise):**
  no live end-to-end check of SSE reattach or the vision pixel gate with a
  real model (unit-tested with TestModel only); renders live in the workdir,
  not the DB; user has not reported memory/compaction issues since the
  `request_limit` change.
- Environment notes: WSL git has no credential helper — push via
  `timeout 90 git.exe -C "G:\\pydantic" push`. Use `docker.exe` from WSL
  (no plain `docker` on Ubuntu PATH). Gates via
  `/mnt/c/Users/norma/.local/bin/uv.exe run`.

## Recently shipped (thickening wave, `9d922da` + this commit)
- R6: artifacts SSE push (`ArtifactStore.watch`, EventSource + poll
  fallback); mermaid fences in spec blocks render to SVG client-side.
- R7: `codingdude eval --record SESSION_ID` + `--scenarios DIR` CI runner.
- R8: `missing-contract` rule, stale-waiver retirement, new
  `adr-contradiction` rule (decision references a module that no longer
  exists → flagged for revisit/retirement; waiverable).
- R9: `ExecutionStore.drift()` (done-without-evidence, out-of-order steps)
  surfaced in `get_resume_state`.
- R10: `session_usage` → `by_model` + `by_request` breakdowns; Cost tab
  renders both.
- R5: container tier (tier param on `sandbox_create`, docker CLI subprocess).

## Next action
Roadmap closed. Brainstorm the next feature wave with the user and open new
`## R<n>` roadmap items.

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

## R5–R10 thickeners shipped (all in one slice)
- **R6 SSE push**: `ArtifactStore.watch()` tails the artifacts table
  (snapshot → emitted/answered deltas); `GET /sessions/{id}/artifacts/events`
  streams it as SSE; the Artifacts panel consumes EventSource live with
  automatic fallback to the old 4s poll on stream error.
- **R7 recording + CI**: `codingdude eval --record SESSION_ID --name N --out
  FILE [--check ...]` exports a real session's persisted messages into a
  scenario; `codingdude eval --scenarios DIR --workdir WD` replays a suite and
  exits 1 with readable FAIL lines (CI-ready).
- **R8 contract-first + ADR hygiene**: archlint gains `missing-contract`
  (public top-level functions/classes under src/ need docstring contracts,
  waivable like any finding) and stale-waiver reporting (a waiver whose finding
  no longer fires is surfaced for retirement).
- **R9 plan diffing**: `ExecutionStore.drift(ticket_id)` flags steps claimed
  done without evidence and out-of-order completion; surfaced in
  `get_resume_state` as a reconcile-before-finishing warning.
- **R10 per-model telemetry**: `session_usage` returns `by_model` rows
  (requests/tokens/cost per model); Cost tab renders the breakdown.
- Gates: 258 pytest passed, ruff clean, mypy clean (39 files), npm build ok.

## R5 tier 2 shipped (container tier)
- Docker verified working after WSL default-distro fix (`wsl --set-default
  Ubuntu`); from the agent's shell the CLI resolves as `docker.exe` (enable
  Docker Desktop WSL integration for plain `docker` inside Ubuntu — optional).
- `sandbox_create(name, tier=''|'worktree'|'container')`: default prefers
  container when `docker_usable()` (CLI + daemon check); explicit
  `container` errors when Docker is unusable — never a silent fallback.
  Container `python:3.12-alpine`, name `codingdude-sb-<name>`, worktree
  mounted at `/workspace`, preview port mapped to container 8000; stale
  container pre-removed so names are reusable. Exec routes via
  `docker exec`; teardown removes the container, then tier-1 teardown.
- Gates: 248 pytest passed, ruff clean, mypy clean (39 files). Ticket #8 closed.
- Environment notes: agent shell is WSL bash; gates run via `uv.exe run`.
  WSL `git` normalization briefly swept CRLF→LF across the repo — commit
  reverted, `core.autocrlf=false` set (repo + global). A `python` shim
  (symlink to python3 in WindowsApps) fixes `python` inside WSL for the
  shell capture-hook test.
