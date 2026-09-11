# 01: See what the agent rendered (visual results + vision-in-the-loop)

Status: ready-for-agent
Type: task
Source: ROADMAP.md → R1

## What to build

CodingDude can **produce** visual results (pixel gate `ss-verify` / `webapp-testing`,
the gate preview, UI shots) but has **no feature to display them**. Give a run's
rendered images a first-class surface and close the vision loop.

Specifically:

1. **Run attachments** — images produced during a run are captured and attached to the
   run/session, surfaced on the trace and/or the chat timeline (not left as orphan
   `.scratch/*.png` files).
2. **A "Renders" surface** — a panel or gallery listing the session's images grouped by
   run, with **light/dark** and **before/after** comparison.
3. **Vision in the loop** — screenshots are routed into the agent's own context (vision
   model) so it can critique what it rendered and iterate the pixel gate to a pass.
4. **Capture hook / skill default** — any render-producing command (screenshot,
   `ss-verify`, `webapp-testing`) automatically registers its output so it is displayed.
5. **Persistence** — renders are persisted with the session (or referenced from the
   trace) instead of relying on gitignored `.scratch/` paths.

## Why

- The agent **cannot see images** through its tool channel, so a visual gate can only be
  *rendered*, never *judged* — the highest-value verification is currently unclosable
  autonomously. (This session reported the gate as "rendered, not verified" for exactly
  this reason.)
- The **user** must open screenshot files by hand; nothing in the UI surfaces them.
- No before/after or light/dark comparison makes appearance regressions easy to miss.

## Acceptance

- After a run that renders a UI, the user opens the session and sees the screenshots
  in-app (dark + light), and can compare against a previous run.
- When running a visual gate, the agent states "verified" only after inspecting an image
  it can actually see.

## Notes / evidence

- Artifacts from the StyleSeed work: `.scratch/ui-dark.png`, `.scratch/ui-light.png`,
  `.scratch/gate-dark.png`, `.scratch/gate-light.png`.
- `webapp-testing` skill note: *"CodingDude routes screenshots to its vision model —
  make sure the PNG actually reaches the model before judging it."* Today it does not.
- Full write-up: `ROADMAP.md` → R1.

## Comments
