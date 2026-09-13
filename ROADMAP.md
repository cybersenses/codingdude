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

## R3 — Context management system
**Status:** done · **Area:** engine / LLM reliability

Shipped: `ContextManager` (token estimation, per-model limits via
`models.context_limit` config or the known-limits table, importance scoring,
`plan_compaction`), token- or char-threshold auto-compaction wired into
`engine.run` with importance-based retention, compaction summaries stored as
retrievable Memory (RAG into future runs' instructions), a persisted
`context_tokens`/`context_limit` snapshot per session (provider-reported input
tokens preferred over the estimate), and a context meter in the session sidebar
(over 80% turns red).

---

## Original R3 problem statement (pre-implementation)

### Problem
CodingDude has **no real context management**. The only mechanism is `_maybe_compact()`,
which summarizes old turns into one message when the history exceeds a threshold. There is:

- No context window monitoring — we don't know how close we are to the model's limit
- No token counting — we estimate by character count, which is inaccurate
- No sliding window — old messages are summarized, not selectively retained
- No importance-based retention — a `git push` approval matters more than a `ls` output, but both are treated identically
- No RAG retrieval — context that falls off the window is gone forever
- No per-model context limits — different models have different windows, we don't adapt
- No automatic compaction trigger — compaction is manual and uses a hardcoded threshold

### Impact
- Long sessions silently degrade: the model loses access to earlier decisions, code, and context
- The context limit can be **overrun without warning**, causing API errors or silent truncation
- Important context (approval decisions, architecture decisions, user preferences) is treated
  the same as throwaway tool output
- The user has no visibility into how full the context is

### Desired behaviour
- A `ContextManager` class that tracks token usage per turn, per model context limits, and
  compaction state
- **Sliding window** with importance scoring: tool results with exit codes > architecture
  decisions > user preferences > small talk
- **Auto-compaction** when approaching the limit: summarize + retain high-importance context
- **Per-model context limits** loaded from the config or provider metadata
- A **`context_usage` field** on the run so the UI can show a context meter (e.g. 78% used)
- RAG-style retrieval of compacted context (the summary is embedded and retrievable)

### Acceptance (rough)
- A run with 200+ messages auto-compacts before hitting the context limit
- Important context (user decisions, approval results) survives compaction
- The UI shows a context usage meter
- Token counting is accurate (within 10% of the provider's count)

---

## R4 — First-class planning data (roadmap, tickets, designs in the database)
**Status:** done · **Area:** product / data model / UI

Shipped: `roadmap_items` / `tickets` / `design_decisions` tables (scoped by project
workdir, survives bounces), CRUD endpoints under `/planning/*`, an agent toolset
(`list_planning`, `update_roadmap_item`, `create_ticket`, `update_ticket`,
`record_decision`), and a Planning tab in the right panel. Closing a ticket
(agent tool or UI) stamps the current HEAD sha as the closing commit.

---

## Original R4 problem statement (pre-implementation)


### Problem
Roadmaps, tickets, design decisions, and handoff docs live as **markdown files the agent has
to remember to update**. They are not in the database, not in the UI, and not automatically
maintained. If the agent forgets to update them, they go stale (which happened with tickets
11/12/14/16 — the engine shipped but the tickets weren't updated).

### Impact
- Planning docs go stale silently — the user trusts them but they're wrong
- Work is invisible — there's no UI surface showing "what are we working on and what's left"
- Cross-referencing is manual — the agent has to read markdown files to know what's done
- No before/after or progress tracking — you can't see how the project evolved

### Desired behaviour
- **Database tables:** `roadmap_items`, `tickets`, `design_decisions` — first-class data with
  CRUD server endpoints
- **UI panels:** a Planning tab (or sidebar section) showing the roadmap, open tickets, and
  design decisions — sortable, filterable, with status indicators
- **Agent tools:** the agent can read/update roadmap items and tickets via tools (not just
  markdown file edits)
- **Auto-sync:** when the agent completes work, the related ticket/roadmap item is updated
  automatically (not by the agent remembering to edit a file)
- **Traceability:** each ticket links to the commits that closed it

### Acceptance (rough)
- The user opens the UI and sees the roadmap, open tickets, and design decisions — no
  markdown files needed
- The agent updates a ticket's status as part of completing work, not as a separate
  documentation chore
- All planning data survives a bounce (stored in SQLite, not in markdown)

---

## Backlog (unscoped)
_Open a new `## R<n>` section per item as it is identified._
