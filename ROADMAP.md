# CodingDude — Feature Roadmap

Product-level shortcomings and the features that would close them. Not a spec:
each item names the **problem**, the **impact**, and the **desired behaviour**.
Status is one of `open`, `in-progress`, `done`.

---

## R1 — See what the agent rendered (visual results + vision-in-the-loop)
**Status:** done · **Area:** observability / verification / UI · **Surfaced by:** the StyleSeed pixel gate

Shipped: an `inspect_image` agent tool (`vision.py`) that routes any Workdir
image through the configured `models.vision` model and returns the critique as
text — so a pixel gate can be judged, not just rendered (IMAGE_INSPECTED trace
events record every inspection); a shell capture hook that auto-registers
image files a command creates as RENDER_CAPTURED events; and Renders-tab
pairing — renders named `*-dark`/`*-light` or `*-before`/`*-after` display
side-by-side as comparisons. The gallery itself (workdir image scan + session
grouping) predates this item.

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
**Status:** done · **Area:** run lifecycle / event stream / UI feedback

Shipped: `/runs/{id}/alive` watchdog probe (true while the run's worker
process lives); the UI no longer fakes a finished run on SSE error — it
reattaches with backoff while the run is alive, says "lost connection" after
repeated failures, and concludes cleanly (reloading persisted messages) when
the worker is already gone; a client watchdog shows "still working… (no
output for Ns)" when a live run is quiet past 30 s instead of looking idle.

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

## R5 — Sandboxed prototype environments (throwaway, previewable, disposable)
**Status:** open · **Area:** execution / prototyping / collaboration

### Problem
The agent runs everything in the user's real working environment. Prototyping
boldly — spinning up 2–3 competing approaches with real servers and databases —
risks clobbering real code. "Prototype with the user" therefore degrades into
talk plus small patches. There is no way to give the user a URL and say "click
this prototype".

### Impact
- Prototypes are conservative and half-real; architecture decisions get made on
  descriptions instead of clickable artifacts.
- Competing approaches can't be tried side by side.
- Failures during prototyping can damage the user's actual workspace.

### Desired behaviour
- One tool call spins up an isolated environment: ephemeral worktree + container
  (or venv) + seeded throwaway DB + preview URL surfaced in the session UI.
- The user can open and interact with each prototype; the agent can render and
  screenshot it (plugging into R1's vision loop).
- Environments are disposable: teardown on demand or when the session ends, with
  nothing written back to the real workdir unless the user promotes it.

### Acceptance (rough)
- The agent builds two competing variants of a small feature in separate
  sandboxes; the user clicks both via preview URLs and picks one.
- Teardown leaves the real workdir byte-identical.

---

## R6 — Living-artifact collaboration channel
**Status:** open · **Area:** UI / collaboration / specs

### Problem
Design collaboration happens through flat chat text. Wireframes, state models,
and specs are prose or static screenshots. The `grilling`/`prototype` skills
interview well, but the *medium* is a text box — the user can't point at a
diagram, edit a spec inline, or pick between rendered options.

### Impact
- Misunderstandings survive until implementation because the user reviews words,
  not artifacts.
- "Pick one" decisions (layouts, state shapes, API designs) are clumsy in prose.

### Desired behaviour
- The agent can emit interactive artifacts to the session UI: editable spec
  blocks, choice cards with side-by-side previews, simple diagrams/wireframes.
- User interactions on an artifact (edits, picks, annotations) flow back into the
  conversation and into planning data (tickets/decisions).
- Skills (`grilling`, `prototype`, `to-spec`) use this channel as their default
  medium.

### Acceptance (rough)
- An ADR or spec written during a session is editable by the user in the UI, and
  the agent reads the edited version on its next turn.
- A "choose between two options" decision renders as two cards; the user's pick
  is recorded as a design decision automatically.

---

## R7 — Session-replay eval harness (regression-test the agent's process)
**Status:** tracer done (thin slice: `codingdude.evals` + `tests/scenarios/`; thickening — real-session recording, curated library, CI promotion — remains open) · **Area:** quality / self-improvement / evals

### Problem
`bench.py` exercises the engine with a scripted model. There is no way to record
a *real* session and replay it as a regression test of the agent's process: did
it ask before assuming, run the verification gates, update the ticket? Process
quality currently regresses silently.

### Impact
- Changes to prompts, skills, or engine behavior can't be validated — we find out
  by living through the regression.
- The self-improvement loop has no measurement; "better" is vibes.

### Desired behaviour
- Record real runs (messages, tool calls, trace events) into a replayable format.
- Replay through the engine with a scripted/mock model and assert on *process*
  properties: gates ran before completion claims, questions asked before
  irreversible steps, planning data updated, verification evidence cited.
- A curated set of recorded scenarios runs in CI alongside unit tests.

### Acceptance (rough)
- A deliberately broken skill (e.g. skips verification) fails the replay suite.
- The current release passes all recorded scenarios.

---

## R8 — Architecture guardrails (linter + contract-first codegen)
**Status:** open · **Area:** architecture / codegen / tooling

### Problem
Codegraph tells the agent what *is* connected; nothing tells it when what it's
*writing* violates the architecture — leaky module seams, duplicated behavior,
config drift. And there is no mechanism that keeps implementation honest against
an approved domain model: the agent can drift from its own spec. Recorded design
decisions are never consulted again.

### Impact
- Architecture erodes one convenient-but-wrong edit at a time.
- Specs and code diverge; the divergence is found in review or not at all.
- ADRs become decoration instead of constraints.

### Desired behaviour
- An architecture linter the agent runs before finishing: flags seam violations,
  duplicated behaviors, and boundary leaks using the deep-module vocabulary from
  `codebase-design`.
- Contract-first codegen: from an approved domain model, emit typed interfaces +
  failing tests as the skeleton; implementation fills the contract.
- ADR enforcement: when a change contradicts a recorded decision, the agent must
  surface the conflict and get the user to explicitly overturn the ADR before
  proceeding.

### Acceptance (rough)
- A PR that reintroduces a known-leaky seam is flagged by the linter.
- A feature built contract-first compiles against generated interfaces and its
  generated tests, and any deviation is an explicit, visible contract change.

---

## R9 — Resumable long-horizon work (crash-safe execution claims)
**Status:** open · **Area:** engine / reliability / planning integration

### Problem
Wayfinder plans multi-session work, but execution state lives in one agent
session. Memory survives a bounce; *in-flight edits and progress* don't. A crash
mid-ticket loses the claim, the partial work, and the verification record.

### Impact
- Long tasks are fragile; recovery is manual archaeology over git status.
- Parallel or handed-off work can double-execute.

### Desired behaviour
- Tickets carry resumable state: claimed-by, plan, step progress, per-step
  verification evidence, so a fresh session picks up exactly where the last left
  off.
- Work claims are crash-safe: stale claims are detected and reclaimable.
- The agent's first move on a claimed ticket is "read the resume state", not
  "re-derive everything from git".

### Acceptance (rough)
- Kill the agent mid-ticket; a new session resumes it with no duplicated work and
  evidence for each completed step.

---

## R10 — Cost and latency telemetry per task
**Status:** open · **Area:** observability / engine / UI

### Problem
Neither the agent nor the user knows what a task cost (tokens, wall time, per
step) until the provider bill. Tradeoffs like "verify deeply" vs "fast draft"
are made blind.

### Impact
- No basis for cost-aware decisions; runaway runs go unnoticed.
- The user can't see where time/money goes (compaction? vision? sub-agents?).

### Desired behaviour
- Per-run and per-step token/cost/latency accounting, persisted with the session
  (R3 already snapshots context tokens — extend, don't duplicate).
- A UI panel showing cost per run/step; trace events carry the numbers.
- The agent can query its own budget mid-run and adapt (e.g. skip optional
  re-verification when over budget).

### Acceptance (rough)
- After a run, the UI shows tokens/cost/duration per step and total, within a
  small margin of the provider-reported usage.

---

## Backlog (unscoped)
_Open a new `## R<n>` section per item as it is identified._

---

## R11 — Per-project reference knowledgebase (curated library manuals)
**Status:** open · **Area:** knowledge / engine / UI · **Surfaced by:** the Pydantic-docs session

### Problem
When the user dropped the actual Pydantic documentation into the workdir, the
agent used it constantly and it measurably improved the quality and speed of
solutions. But this only worked because the user manually fetched the docs —
there is **no built-in place or workflow** for per-project reference material:

- No convention for where manuals live or how they get indexed.
- The agent has no way to *discover* or *query* the reference corpus; whether
  it helps depends on whether a file happens to be grep'd at the right moment.
- Docs go stale: nothing tracks which library version a manual covers vs. what
  the project actually uses.
- The pattern (fetch → store → retrieve) must be repeated by hand every project.

### Impact
- The single highest-leverage context intervention observed so far stays
  accidental instead of systematic.
- Hallucinated/outdated API usage persists when no manual is present.
- RAG summaries (R3 compaction) cover *this session's* history only — there is
  no durable, project-scoped knowledge layer.

### Desired behaviour
- A **per-project `references/` folder** (or tracked store) where manuals,
  API docs, ADRs of dependencies, etc. are stored — user-supplied or
  agent-fetched on demand ("pin the pydantic v2 docs for this project").
- **Agent tooling to use it:** a `search_references` / `read_reference` tool so
  retrieval is deliberate and cheap, not a lucky grep. Index at ingest
  (section-level), not at query time over raw dumps.
- **Freshness awareness:** each reference records the library version it
  documents; the agent is warned (or the reference flagged) when the pinned
  dependency in `pyproject.toml`/`package.json` diverges.
- **Skill guidance:** skills like `ss-setup`/`implement` prompt to check whether
  relevant references exist before relying on model memory.

### Acceptance (rough)
- A user can add a manual (file or URL) to a project and the agent can find and
  cite the right section mid-task without the user naming the file.
- A deliberately outdated manual produces a visible staleness warning tied to
  the dependency pin.

### Evidence / notes
- Proven pattern: ingesting real Pydantic docs during a session let the agent
  resolve multiple integration issues it would otherwise have guessed at.
- Rides on the existing workdir-scoped Memory infrastructure (R3) — likely an
  additional store + tools, not a new retrieval engine.
