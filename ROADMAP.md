# CodingDude — Feature Roadmap

Product-level shortcomings and the features that would close them. Not a spec:
each item names the **problem**, the **impact**, and the **desired behaviour**.
Status is one of `open`, `in-progress`, `done`.

---

## R1 — See what the agent rendered (visual results + vision-in-the-loop)
**Status:** open · **Area:** observability / verification / UI · **Surfaced by:** the StyleSeed pixel gate

### Problem
CodingDude (and its skills) can **produce** visual results — screenshots from the
pixel gate (`ss-verify` / `webapp-testing`), the gate preview
(`.scratch/gate-preview.py`), UI shots (`.scratch/ui-shots.py`) — but there is **no
feature to display them**:

- The agent **cannot see images** through its tool channel, so a visual gate can
  only be *rendered*, never *judged*. During this session the gate was reported as
  "rendered, not verified" for exactly this reason.
- The **user** must open files by hand (`.scratch/ui-dark.png`, `.scratch/gate-dark.png`).
  Nothing in the UI surfaces them.
- Renders land as **gitignored scratch files** with no link to the run/session that
  produced them; they are not attached to a message, the trace, or the session.

### Impact
- The **pixel gate stops at render** — the highest-value verification (does it
  actually look right?) cannot be closed by the agent autonomously.
- Rendered evidence is effectively invisible unless someone remembers the path.
- No before/after or light/dark comparison, so regressions in appearance are easy to miss.

### Desired behaviour
- **Run attachments:** images produced during a run are captured and attached to the
  run/session (surfaced on the trace and/or the chat timeline), not left as orphan files.
- **A "Renders" surface:** a panel (or gallery) showing the run's images grouped by run,
  with **light/dark** and **before/after** side-by-side.
- **Vision in the loop:** screenshots are routed into the agent's own context (vision
  model) so it can critique what it rendered and iterate the pixel gate to a pass.
- **A capture hook/skill default:** any render-producing command (screenshot, `ss-verify`,
  `webapp-testing`) automatically registers its output so it is displayed.
- Persist renders with the session (or reference them from the trace) instead of relying
  on ignored `.scratch/` paths.

### Acceptance (rough)
- After a run that renders a UI, the user opens the session and sees the screenshots
  in-app (dark + light), and can compare against a previous run.
- The agent, when running a visual gate, states "verified" only when it has actually
  inspected an image it can see.

### Evidence / notes
- Session artifacts: `.scratch/ui-dark.png`, `.scratch/ui-light.png`,
  `.scratch/gate-dark.png`, `.scratch/gate-light.png`.
- `webapp-testing` skill note: *"CodingDude routes screenshots to its vision model —
  make sure the PNG actually reaches the model before judging it."* Today it does not
  reach the agent.
- The `ss-verify` pixel gate is currently **skipped/rendered-only** in CodingDude.

---

## R2 — Agent appears to hang after the user replies
**Status:** open (potential, needs repro) · **Area:** run lifecycle / event stream / UI feedback

### Problem
During a session the user replied to a question but the agent showed no visible response for a
while — it looked hung — until they prodded ("did you hang up on the last task?"). It is unproven
whether the run was actually stalled, the UI failed to show progress, or an event was dropped.

### Impact
Users can't tell whether the agent is working, waiting, or dead — so they re-prompt or lose trust.

### Desired behaviour
- An immediate, unambiguous "working" state when a reply starts a run.
- A watchdog: if a run is alive but emits nothing for N seconds, show "still working…" instead of
  looking idle.
- Guarantee every user reply reliably starts (or resumes) a run, with a clear error when it can't.

### Evidence / notes
- Observed 2026-09-11: after the user answered a question the agent appeared to hang; the user
  asked "did you hang up on the last task?", after which it continued.
- Suspects: run-start not surfaced promptly; a dropped/missed SSE or gate event; a polling gap.
- Needs a repro and a look at the worker → server → SSE path and the UI run-state indicator.

---

## Backlog (unscoped)
_Open a new `## R<n>` section per item as it is identified._
