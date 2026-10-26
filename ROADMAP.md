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
**Status:** done (tier 1 `b3ceefd`: worktree+venv lifecycle; tier 2: container tier — `sandbox_create` tier param, docker CLI subprocess, worktree mounted at `/workspace`, preview port mapping, gated promote unchanged) · **Area:** execution / prototyping / collaboration

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
**Status:** done — SSE push channel (`/sessions/{id}/artifacts/events` via `ArtifactStore.watch`); Artifacts panel consumes live events with poll fallback; ```mermaid fences in spec blocks render to SVG client-side (render-only). · **Area:** UI / collaboration / specs

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
**Status:** done — real-session recording (`codingdude eval --record SESSION_ID`) + CI runner (`codingdude eval --scenarios DIR`, exit 1 on failure). Curation shipped: `keep_for_evals` session marking, timestamped session notes (run + offset), notes ride on `export_scenario`, Notes tab in the session panel (docs/specs/R7-curation-notes.md). Curated scenario *library* deliberately deferred (content, not mechanism). · **Area:** quality / self-improvement / evals

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
**Status:** done — `missing-contract` rule + stale-waiver ADR hygiene + `adr-contradiction` rule (a recorded decision referencing a module that no longer exists is flagged for revisit/retirement; waiverable). Deliberately deferred (information-thin): codegen from contracts. · **Area:** architecture / codegen / tooling

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
**Status:** done — `ExecutionStore.drift()` plan diffing (done-without-evidence, out-of-order steps) surfaced in `get_resume_state` · **Area:** engine / reliability / planning integration

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
**Status:** done — `models.pricing` config, RUN_USAGE event, `by_model` and `by_request` (chronological per-request rows) breakdowns; Cost tab renders both. · **Area:** observability / engine / UI

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
**Status:** done (tracer `6d5a799`: ReferenceStore with incremental section index, search/read/staleness tools wired into `plugins.build_all`) · **Area:** knowledge / engine / UI · **Surfaced by:** the Pydantic-docs session

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

## R12 — Deterministic file-edit pipeline (edit_file reliability)

**Status:** done (commit `8f7a62d`; ticket #15 closed; 293 pytest, ruff/mypy clean).

### Problem
`edit_file` has corrupted files in 3+ recorded incidents (duplicated lines,
silent revert, a rewritten Notes component). Gates caught each, but every
incident cost a scripted-patch workaround. Root cause diagnosed in `tools.py:edit_file`:

1. `read_text(errors='replace')` — non-UTF-8 bytes become U+FFFD, and the
   write **persists the damage**.
2. Universal-newline round-trip converts LF files to CRLF on Windows Python —
   mixed line endings make the file look subtly corrupted.
3. No atomicity and no staleness check — concurrent writers resolve to
   last-writer-wins, observed as "silent revert".

### Desired behaviour
- Bytes-safe read: strict decode, non-UTF-8 → readable `ModelRetry`, never
  written back damaged.
- Newline-preserving round-trip (`newline=''` read/write).
- Atomic write: temp file + rename.
- Post-write verification: re-read, assert expected content, rollback on
  mismatch.
- Staleness guard: refuse (retryable) if the file changed on disk since the
  agent last read/edited it.

### Acceptance
- Tests reproduce the three observed corruption modes at the FunctionToolset
  seam; `write_file` shares the same write primitive.

### Evidence / notes
- Decision #8. Spec: `docs/specs/R12-edit-pipeline.md`.


---

## R13 — Isolated delegated agents

**Status:** done (ticket #19)

**Theme (b): long-horizon / multi-agent orchestration.** `delegate` today runs
unisolated in the main workdir and returns one opaque blob.

### Scope
- Delegated sub-agents run in a **worktree sandbox by default** (R5 tier-1);
  container tier when the parent flags the task risky; merge only via
  `sandbox_promote` (approval-gated).
- **Nested-run visibility**: `DELEGATION_STARTED` / `DELEGATION_PROGRESS` /
  `DELEGATION_COMPLETED` trace events; UI shows delegation as a nested run with live output.
- **Inherited approvals**: delegation tool calls resolve through the parent
  run's approval policy — no separate grant path.
- **Budget ceiling**: config-driven `max_requests` / `max_cost_usd` per
  delegation; abort with readable `ModelRetry`; cost attributed to the parent
  session via R10 telemetry.

### Explicitly out of scope
- Wayfinder / cross-session handoff plumbing in code — the R9 state layer
  already exists; it stays a skill concern.

### Evidence / notes
- Decision #9 (round 4, approved). Spec-level only this session.

## R14 — Contract-first discipline + mid-run index refresh

**Status:** done

**Theme (c): deeper code understanding.** Thin slice of the deferred R8
contract-first codegen; no DSL, no generated stubs.

### Scope
1. **Contract convention**: specs may carry a  section — typed
   signatures + test names the implementation must satisfy.
2. **Archlint rule**: every exported symbol named in a spec's Contract section
   must exist in code and be referenced by at least one test; violation = soft
   finding (fix or explicit waiver, matching R8's model).
3. **Mid-run refresh**: codegraph index + archlint re-run best-effort after
   each fix-loop iteration so long sessions don't lint stale code.

### Deferred until R12 lands and proves out
- Generated interface stubs, contract DSL, automatic conformance checking.

### Evidence / notes
- Decision #10 (round 5, approved). Spec-level only this session.

## R15 — Research pipeline

**Status:** done

**Theme:** curated web research persisted into the reference knowledgebase.

### Shipped
- `src/codingdude/research.py`: `build_research_toolset(workdir)` -> `save_research(topic, markdown, replace=False)` writing `reference/research/<slug>.md`.
- Validation: non-empty doc, `As of:` stamp, at least one source URL; refuses clobber unless `replace=True`.
- Process discipline in tool docstring: decompose into subtopics, <=5 reliable sources per subtopic, +5 escalation only on wild disagreement, soft ask_user validation gate, freshness via human-triggered re-research.
- Registered in `plugins.build_all`; saved docs auto-index into ReferenceStore (`search_references`) — no new retrieval path.

### Evidence
- Commit `2127571`; 312 pytest passed (+7 in `tests/test_research.py`), ruff clean, mypy clean.

## R16 — Delegation task briefs (subagent context shipping)

**Status:** done (ticket #21, commit `ff39a2b`).

### Problem
Delegated subagents received only the raw `task` string — no verified symbols, no
contract excerpts, no budget — so they re-explored the codebase from scratch and
drifted out of scope.

### Shipped
- `DelegationBrief` (verified symbols + contract excerpt + request budget) compiled
  into the subagent system prompt by `build_brief` / `brief_prompt`.
- `delegation_id` links DELEGATION_STARTED/COMPLETED trace events to the parent run.

## R17 — Write-capable delegation via sandbox exec

**Status:** done

### Problem
Delegation was read-only; any change required the parent to do the editing, which
defeated the point of delegating implementation work.

### Shipped
- `delegate(task, write=True)` grants the subagent exactly one extra tool:
  `exec_in_sandbox`. Writes stay in the sandbox tier.
- The subagent changes cross back to the parent as a git diff — the main tree is
  never touched directly, and no-sandbox environments error without mutating anything.

## R18 — Non-blocking post-run tail

**Status:** done

### Problem
Memory extraction (one bounded LLM call, ~24–90s) blocked , so
the user stared at a spinning UI for up to ~90s after every run — pure friction.

### Shipped
-  returns immediately after usage accounting; extraction ∥ claims
  audit run as a background tail () — same events, same 120s caps.
- The next turn drains pending tails (, 300s bound)
  before its prompt is assembled, so extraction always lands before it matters.
-  public for shutdown/tests; silent extraction catch now
  logs with context.

## R19 — Project bootstrap defaults

**Status:** done

### Problem
New projects (observed on BreweySoft) start bare: no reference folder, no
codegraph index until first-run auto-bootstrap, no ROADMAP.md scaffolding.
The agent has to be told what "ready" looks like.

### Proposed
ensure_project_scaffold(workdir) run at project creation / first session:
reference/ (+ reference/research/), .codegraph init (reuse
ensure_codegraph_index), ROADMAP.md stub with the standing-rules header,
optional CONTEXT.md stub. Idempotent; never clobbers existing files.

### Shipped
- Codegraph boot with visible outcome: `boot_codegraph` (#33, b1172bd).
- `ensure_project_scaffold` (#31): idempotent creation of reference/,
  ROADMAP.md, CONTEXT.md; wired into engine.run beside boot_codegraph;
  scaffold results ride the CODEGRAPH_BOOT trace event.

## R20 — Roadmap-vs-ticket guidance (agent logs tickets when asked to log roadmap items)

**Status:** done

### Problem
When the user says "log this on the roadmap", the agent logs a ticket instead.
Process guidance is missing: tickets and roadmap items are different artifacts
(ticket = unit of work; roadmap item = R<n> section in ROADMAP.md, canonical).

### Proposed
1. Strengthen the standing rule in the agent's system prompt / project notes:
   every roadmap-worthy request creates BOTH an R<n> section (ROADMAP.md,
   via upsert_roadmap_md) AND a tracer ticket, linked by R-id.
2. Add a `log_roadmap_item(title, body)` convenience tool that does both in
   one call, so the agent cannot get it wrong.
3. Planning tab already reads ROADMAP.md (md-as-source-of-truth) — no UI work.

## R21 — Shell tool: pipe-inheritance hang in run_captured
**Status:** done

Fixed (ticket #34): run_captured polls proc.returncode instead of communicate()/proc.wait() (both wait for pipe EOF on Windows; a grandchild inheriting stdout/stderr kept finished commands blocked to timeout, killed and output lost). Kill only if still running at deadline, then drain pipes with 1s-per-readline grace. Regression: tests/test_run_captured.py::test_run_captured_returns_when_parent_exits_despite_grandchild. Side effect: git push no longer hangs. on Windows. Root cause confirmed: `run_captured` (tools.py:97) awaits `proc.communicate()`, which waits for pipe EOF, not process exit. A grandchild inheriting stdout/stderr keeps the pipe open after the parent exits, so the tool blocks to timeout, returns "timed out", and loses real output. Reproduced deterministically: `.scratch/repro_shell_hang.py` (parent exits 0.1s, run_captured(timeout=5) waits full 5s → None). Also explains earlier git push "hangs" and possibly the 261s mid-session stall.

## R22 — AST-powered agent understanding (structural edits + semantic diffs)
**Status:** done

Leverage the existing tree-sitter/codegraph AST infrastructure (already used for navigation, dead-code, arch-lint) in two spots with observed payoff:

1. **Symbol-based edit application** — edit tool that takes (symbol, new body) instead of line offsets; eliminates stale-edit "file changed since read" refusals.
2. **AST-aware diff/claims feedback** — parse before/after, report semantic changes (symbols touched, signature changes) to strengthen claims verification and post-edit feedback.

Explicitly out of scope: ASTs as a replacement for LLM intent understanding; building type/dataflow analysis (mypy/pyright already gate this).

Assessment: viable, low-medium effort per item, reuses existing parsers.

## R23 — CI stability on GitHub Windows runners
**Status:** done

14 test failures in CI (run 34984478320) that pass locally on the dev machine: test_sandbox (6), test_interactive_approvals (2), test_mcp, test_render_persistence, test_server, test_shell (2), test_tools. Likely Windows-runner environment differences (temp paths, spawn behavior, git config). Goal: CI green so GitHub notifications only fire on real regressions.

## R24 — R22 — File-tools hardening: unique atomic-write temp names
**Status:** done

`_atomic_write` (tools.py) uses a deterministic `<name>.codingdude-tmp` path; two concurrent writers to the same target collide and the second open() fails with WinError 32. Repro: .scratch/repro_tmp_collision.py (399/400 collisions). Fix: unique tmp name + retry on PermissionError for os.replace.

## R25 — Tool runtime errors feed back to the agent (3 strikes)
**Status:** done

Unexpected exceptions inside tools (OSError/WinError 32, NameError, ...) used to propagate out of the toolset and kill the run immediately. codingdude/tool_errors.py adds a ToolErrorFeedback wrapper toolset: unexpected tool exceptions become ModelRetry messages the model can act on (tool name + cause + hint). Control-flow exceptions (gates, approvals, deferrals, cancellation, ToolFailed) pass through untouched. Retry budget raised from 2 to 3 (PromptAssembler.agent default), so the agent gets 3 tries to self-correct before the run aborts. Wired for the main agent (engine.run) and delegation sub-agents. Tests: tests/test_tool_errors.py.

## R26 — R26 — Multi-language tooling support (parked assessment)
**Status:** done

Minimum language support: C#, C++, C, JavaScript, TypeScript, HTML, CSS, Rust, Go, Kotlin.

Tier 3 (full: edit_symbol + AST diff + navigation) via tree-sitter registry `langs.py`:
- Already shipped grammars: JavaScript, TypeScript (jslang.language_for)
- To add: tree-sitter-c, -cpp, -c-sharp, -rust, -go, -kotlin
- edit_symbol / describe_ast_change / find_definition / find_references dispatch via registry; Python keeps stdlib-ast path
- Tracer: TypeScript first (grammar exists)

Tier 2 (HTML/CSS): navigation only — symbol semantics differ (tags/selectors); no structural edit_symbol.

Approved plan (2025): registry → TS tracer → grammar batch → HTML/CSS tier-2. Risks: Kotlin grammar maturity, brace-language indentation, CRLF re-verification per language.

**Question answered:** file-level tools (read/edit/grep/glob/run) are language-agnostic today; symbol-level intelligence is Python-only.

Per-tool status:
- Python-only (stdlib ast): edit_symbol, describe_ast_change, find_definition, find_references, arch_lint
- Multi-language (tree-sitter): codegraph (search/callers/callees/impact), find_dead_code (vulture + JS/TS tree-sitter)
- Language-agnostic: file tools, run_command, gates (configured), sandbox/worktrees/delegation

Gaps to close only if broad language support becomes a requirement:
1. Extend edit_symbol/AST diffs to tree-sitter grammars (per-language symbol queries; brace/indent semantics differ) — the natural path, parser already shipped.
2. Verification gates: pytest/ruff/mypy contract is Python-specific; other languages need their own gate config.
3. Dead-code/lint coverage thin outside Python + JS/TS.

Decision: do NOT build speculatively. Revisit when a non-Python project becomes real usage.

## R27 — R27 — Edit-tool match hardening (aider-style SEARCH/REPLACE matching)
**Status:** done

Port aider's layered matching (exact, whitespace-flexible, blank-line tolerance, `...` elision — skip fuzzy) into edit_file via new editmatch.py, plus did-you-mean feedback on no-match. Keep all existing safety: uniqueness rule, _atomic_write, write-verify+rollback, staleness, CRLF byte-faithful handling, AST summary.

## R28 — Process registry: tracked shell processes with HITL visibility
**Status:** done

**Problem (from myai usage):** agent spawns background/detached processes; when the parent shell exits the agent loses track, and HITL has no visibility of running shell processes.

**Decision:** spawned processes survive as **registered orphans** — tracked, killable, cleanable later. True **interactive stdin** is required (agent can write to live processes). Build phased:

- **Phase 1** — visibility-only ProcessRegistry: shell tool records command/pid/started/status; trace events + `/processes` endpoint so HITL sees every process. No behavior change. Uses the R21 exit-fast signal to flag spawned-background children.
- **Phase 2** — agent tools over the registry: `kill_process`, `poll_output` (and stdin write); approvals apply to writes.
- **Phase 3** — persistent interactive shell sessions (PTY), streaming output to frontend via SSE.

**Windows note:** Job Objects are the correct tracking primitive (PIDs recycle; killing parents doesn't kill children). R21 pipe-EOF logic lives at this layer.

## R29 — Frontend reconnect resilience: resume live run after crash/reopen
**Status:** done

**Problem (from myai usage):** frontend crashed mid-run; on reopen, chat did not reconnect or catch up to the run's progress. SSE mid-run reattach exists server-side (E2E-tested) but the frontend doesn't exercise it on boot. Scope: on load, check `/runs/{id}/alive` and reattach to the live stream; render missed events; surface reconnect state in UI.

## R30 — R30 — Post-run tail: zero-wait run finish + faster memory extraction
**Status:** done

Zero-wait run finish + faster extraction. Verified live: RUN_FINISHED lands immediately; extraction ~12s; MEMORY_EXTRACTED before/after tail confirmed; UI settles instantly, stop-button flicker (worker-alive-during-tail listed as active) fixed via active_runs excluding terminal-delivered channels (752e080).

Shipped `76f57d7` (tickets #59/#60): RUN_FINISHED emits immediately after persistence; pending tail drains afterwards (bounded 150s, before worker exit) so extraction is never lost. Extraction input trimmed (known 50→25, transcript 12000→6000). Verification pending: next live run should show UI settle in <1s at RUN_FINISHED with MEMORY_EXTRACTED landing shortly after in the trace.

Observed live: run settles only ~94s after work completes because worker._finish_run drains the post-run tail (memory extraction) BEFORE emitting RUN_FINISHED. User-perceived wait budget: 15s. Two work items: (1) emit terminal event first, then drain tail bounded before worker exit; (2) shrink extraction input/prompt to cut actual extraction latency.

## R31 — R31 Run-end determinism & process visibility
**Status:** done

Worker still wedges after drain on some runs (trace ends at MEMORY_EXTRACTED, worker never exits; UI stuck until manual stop) — recurring Windows asyncio/Proactor teardown wedge. Two-pronged: (1) make worker teardown fail-safe so it can never hang the UI, (2) surface every spawned process in the UI until it exits, so hangs are diagnosable from the frontend instead of trace archaeology.

## R32 — Language registry expansion: Java, PHP, config languages, Bash
**Status:** done

Per research (reference/research/language-support-priorities.md): add Tier 3 Java + PHP, Tier 2 JSON/YAML/TOML (HTML/CSS pattern), Bash. R26 batch pattern: `_<lang>_spec()` in langs.py, suffix branch in spec_for, pyproject deps, tests.

## R33 — R33: Review automation (Bito-inspired)
**Status:** done

Mirror Bito's highest-value capabilities: automated PR summaries and automated code review with fix application. Research source: bito.ai (PR review agent, one-click fixes, model router). Model router deliberately deferred — lowest alignment with current trajectory.

Shipped: #66 pr_summary tool (commit list + diff stat + AST semantic summaries, `0cc5c28`); #67 post-push review directive — git_push returns the pushed range and mandates the review→verify→fix→gates loop, never auto-pushes (`e445c05`); #68 review checklist mandates codegraph impact analysis + verified-only findings (`404ca97`).

## R34 — R34: Human interface & cowork (Monaco editor)
**Status:** done

Overhaul the human interface for cowork: humans can see, browse, and edit code alongside the agent. Monaco editor (microsoft.github.io/monaco-editor) as the editing surface, backed by a sandboxed server file API. All writes — human or agent — go through the same validation rails (workdir sandbox, atomic write, staleness registry).

## R35 — IDE layout (VS Code-inspired)
**Status:** done

Restructure frontend to VS Code spatial grammar: activity bar, center editor (Monaco tabs), right agent-chat panel, bottom dock (Terminal/Trace/Processes), status bar. Deliberately not a 1:1 copy — visual identity stays ours; uniqueness: agent chat as first-class, trace stream, HITL approvals.

Phases:
1. Move existing panels to VS Code positions (Files/editor center, chat right, dock bottom).
2. Activity bar + bottom dock structure.
3. Visual identity pass.

## R36 — R36: Agent-core hardening (decomposition, token accounting, vision)
**Status:** done

Informal backlog formalized: engine.run decomposition (maintainability of the highest-traffic method), H7 streaming-vs-usage token accounting (reconcile streamed deltas vs final usage), R1 vision half (engine-side image attachment/passing).

## R37 — R37: Selection AI actions in editor
**Status:** done

User highlights code in the editor and gets one-click agent actions (Explain, Fix, Optimise, Improve, …). Each action starts a scoped agent run on the selected snippet.

## R38 — R38: Visual aids (waterfall, semantic diff summary, impact graph)
**Status:** done

Big-picture visual aids for humans, per reference/research/agent-activity-visualization.md (all zero/minimal new deps).
Phase 1 — Run waterfall: hand-rolled SVG span timeline (TOOL_CALL_START/END brackets, delegations nested) in a new DockPanel tab; optional Chrome Trace Format export.
Phase 2 — Semantic change summary: reuse astdiff.describe_ast_change beside the Diff tab; extend TS via tree-sitter.
Phase 3 — Dependency/impact mini-graph: AST/tree-sitter import edges for edited files rendered via existing Mermaid flowchart component.

## R39 — Skill rigor upgrades (from agency-agents review)
**Status:** done

Adopt 4 ideas from the agency-agents repo review into our skill library: standard skill skeleton with success signals, post-mortem template + hypothesis timebox in diagnosing-bugs, triage markers + no-drip-feed in code-review.

## R40 — R40 — Engineering persona distillation
**Status:** done

Adopt behavioral techniques (not personas) from agency-agents Engineering Division: (a) Minimal Change Engineer scope discipline into surgical-patch; (b) three-level explanation + inspection-coverage honesty into caveman-explore.

## R41 — R41 — Persona checklist distillation + specialty-actions seam
**Status:** done

Strip the idea-value from all agency-agents personas (~130, 23 divisions) into versioned reference checklists per specialty, indexed via search_references. Later: a specialty-actions seam so users can invoke these as actions on the systems CodingDude builds. Explicitly NOT adopting personas as identity.

## R42 — R42 — Human code comprehension (user-facing views of generated code)
**Status:** done

Second feature thrust: tools that help a HUMAN understand the code the agent generates — call graphs, structure views, dependency maps of the produced code itself (not run telemetry). Audience shift: agent introspection (R31/R35/R38) stays, but new work must derive from user value.

## R43 — R43 — Human comprehension wave 2 (research-backed)
**Status:** done

From reference/research/human-code-comprehension.md (As-of 2026-09-20). Five user-facing features: repo Q&A with citations, module architecture map (C4-lite), trust-my-tests report, code tour of a run, auto design doc/ADR.

## R44 — R44 — Friction fixes from SteroidsEngine usage
**Status:** done

Fixes surfacing from real SteroidsEngine usage.

## R45 — Static analysis: control-flow graphs
**Status:** done

CFG of basic blocks per function, unreachable-code analysis, green/red Mermaid HTML render (user request).

## R46 — R46 — CFG analysis for agent + HITL
**Status:** done

Control-flow graph analysis exposed both ways: agent tool (dead-code detection during work) and human UI panel (green/red basic-block view of generated code). Build on cfg.py::build_cfg seam from #152.

## R47 — R47: Analysis hardening
**Status:** done

Security + verification gates from the local-agent tooling research. Adopt: T1 security gate on edits (Bandit + gitleaks), T2 mutation testing into trustreport (mutmut), T3 conditional Semgrep custom rules, T4 parked perf smoke (cProfile tool). Rejected: Zoekt/SCIP, Joern/CodeQL CPG, symbolic execution, Docker sandbox (per existing design decision), local LLM.
## R48 — Project onboarding: convention discovery on first run

**Status:** done

An agent taking over a project (from another agent or fresh checkout) had no
enforced step to discover where work is tracked, so work went unlogged.
Closed by: first-run onboarding (no 'Project conventions:' workdir memory ->
directive injected into instructions, PROJECT_ONBOARDING surfaced in the
CODEGRAPH_BOOT event); the agent must discover tracker/gates/docs, confirm
with the user, and bank a durable memory record. Standing built-in directive:
open a tracked item before non-trivial work. Tests: tests/test_onboarding.py.

## R49 — R49: Referential solutions memory
**Status:** done

Referential memory: structured problem→solution records (kind='solution' in the memory table), a record_solution/lookup_solutions tool pair, and forced recall — solutions are always injected into session instructions (bounded), not left to RAG chance. Motivated by repeated identical mistakes across SkyborneRealms sessions.

## R50 — User-managed LLM configuration
**Status:** done

Expose model/provider configuration as a managed, validated resource: GET/PUT /config/models, GET /config/providers (key presence only, never values), validated atomic writes with pre-save model construction, plus a frontend Settings page.

## R51 — R51 — Open-source release: AGPL-3.0 + dual licence + CLA + trademark
**Status:** done

Open-source release under AGPL-3.0 with dual commercial licensing, trademark protection, CLA, and generated-code-ownership terms. Plan id 40.

## R52 — Product requirements & technical design docs
**Status:** done

Gap: repo had per-feature specs and ADRs but no product-level PRD or technical
design doc — and no general tooling for either. Closed by: PRDs and tech designs
as first-class planning artifacts (mirroring R4 roadmaps/tickets) — `prds` and
`tech_designs` SQLite tables, CRUD endpoints under `/planning/prds` and
`/planning/designs`, six agent tools (`create_prd`/`read_prd`/`update_prd`,
`create_tech_design`/`read_tech_design`/`update_tech_design`), Planning-tab UI
sections, and `prd` + `tech-design` skills shipped to every project via
`.codingdude-seed/skills/`. Mirrored to GitHub issue #14.

## R53 — Automatic GitHub issue mirroring for planning items
**Status:** done

Standing convention (user-mandated): every ticket/roadmap item is logged
locally first, then mirrored to a GitHub issue — enforced in code because
agent discipline proved unreliable. Closed by: `gh_mirror.py` (`GitHubMirror`
— best-effort gh CLI boundary: create issue, close as completed, ensure green
`done` label; probes gh/remote/auth once per workdir and never blocks or
raises), additive `gh_mirror` mapping table (workdir, kind, local_id →
issue_number), hooks inside `RoadmapStore` creates/done-transitions plus the
ROADMAP.md paths (agent toolset and server endpoints), and a
`[planning] github_mirror` config knob (default on). Graceful skip when gh,
auth, or a GitHub remote is absent. Mirrored to GitHub issue #55.

## R54 — Fix silent lost-update race on parallel same-file edits
**Status:** done

Root cause of recurring "edit reported success but didn't persist": parallel tool calls in one block run concurrently; two edits to the same file both read the same `before`, and the second atomic write clobbered the first (lost update) while both reported success. Reproduced deterministically with a two-thread probe. Fix: per-path `threading.Lock` serializing the whole read→write→observe critical section in build_toolset (wrapper on edit_file/write_file/edit_symbol). Regression test test_parallel_same_file_edits_both_survive (red pre-fix, green post-fix). Gates: 779 passed/1 skipped, ruff+mypy clean.

## R55 — Fix worker exit code 2: dash-leading run_id breaks argparse
**Status:** done

Run ids from `secrets.token_urlsafe` can start with '-'; argv `--run-id -x...`
then fails argparse parsing (exit 2) before the worker logs a single line —
surfacing as "worker exited unexpectedly (code 2) without finishing the run".
Fix: regenerate run ids until option-safe, plus a regression test.

## R56 — Docker smoke-test of setup/install path
**Status:** done

Verified in python:3.12-slim Docker container. uv sync works (needs full source incl. README — no pre-sync layer split possible). ruff clean; mypy reports 2 Linux typeshed false positives (restart.py Windows creation flags, code correctly os.name-guarded). pytest: 765 passed, 9 failed, 7 skipped — all 9 failures platform-specific (need docker CLI, gh stub path, Windows process-tree semantics). Server boots, seeds ~/.codingdude, /health OK (v0.4.0), serves freshly built UI incl. compressed logo. Windows-only steps (winget gh, github-mcp.exe, codegraph npm -g) don't apply on Linux by design. Artifacts: docker/Dockerfile.verify + .dockerignore committed. Semgrep not installed in image (security gate degrades to bandit/regex mode there); codegraph npm -g is platform-independent but was not installed. /health checked via docker exec (server binds 127.0.0.1). Build: docker build -t codingdude-verify -f docker/Dockerfile.verify .

Validate the install path end-to-end on a bare Linux environment via Docker: uv sync, gates, frontend build/serve, server /health boot. Document Windows-only steps that don't apply.

## R57 — SQLite 'database is locked' lockup: shared connection, no write serialization
**Status:** done

## Problem
Intermittent `sqlite3.OperationalError: database is locked` that hangs a run and the UI
("completely locked up"). Recurring: first observed 2026-09-28 (`RUN_ERROR` in trace
`G0SUN1seqSI`), still occurring 2026-10-20 during a docs edit + commit run.

## Prior mitigation (R-not recorded, shipped ~Sep 28)
`db.py`: `PRAGMA busy_timeout=15000` + `Database._commit()` retries 3× with 50/100/200 ms
backoff. This only *widens the window*; it does not serialize writers.

## Evidence (2026-10-20)
- `~/.codingdude/codingdude.db` 28.6 MB, `codingdude.db-wal` **25.5 MB** and growing —
  checkpoints are starved, i.e. a long-lived read snapshot or an orphaned transaction.
- Only one server (pid 8808) and one worker (pid 23868) alive; no stale processes, so the
  lock is transient contention, not a leaked handle.
- Server stdout is not persisted (`server.log` holds only the banner) — the failure is
  invisible after the fact. Diagnosability gap.

## Findings (measured by the #223 harness; supersedes the suspicions below)
1. **No rollback, anywhere.** At diagnosis time no `rollback()` call existed in
   `src/`. Python's `sqlite3`
   opens a transaction before DML and leaves it open when a statement raises, so the
   doomed transaction keeps SQLite's write lock. Measured: after a rejected write
   `in_transaction` was `True`, and a second connection then failed with
   `database is locked` after 16.4 s (i.e. it waited out `busy_timeout` first). A
   long-lived process never releases it — this is the lockup, not the retry budget.
2. **`append_messages` sequence allocation was not atomic.** `MAX(seq)+1` then INSERT
   hands two concurrent appenders the same `seq`; the second trips
   `UNIQUE (session_id, seq)`. The server writes the user turn while the worker writes
   assistant turns to the same session, so the collision is by design, not by accident.
   `record_usage` alone (no sequence) never failed in the same 4-writer race.
3. **One connection shared across the server threadpool** is not a transaction boundary;
   CPython reports `InterfaceError: bad parameter or other API misuse`.
- Falsified: *lazy cursor iteration* (`references.py:177`) is `fetchall()`'d, so it pins
  no snapshot; and the retry budget was never the limit — the failures are structural.

## Progress
Phase 1 + fix landed with ticket #223. `Database` now connects through a
`sqlite3.Connection` subclass whose `execute`/`executemany`/`executescript` roll back
and re-raise, and whose `commit` retries while write-locked then rolls back — between
them covering `db.py` and every module that reaches `db._conn` directly, including the
31 call sites that commit through the raw connection; sequence allocation is a single
`INSERT ... SELECT`; and each thread gets its own connection via `threading.local`.
`tests/test_db_contention.py` asserts the three symptoms (red before, green after), and
`tests/test_db.py` covers the commit path (retry, give up, direct commit, rollback,
and the two interrupt cases).
Remaining: WAL ceiling/checkpoint policy. Server errors are now persisted to
`logs/server.log` — #239 landed: `configure_file_logging()` attaches the root
file handler (factored out of `serve()`), and the `strip_api_prefix` middleware
emits a `REQUEST_FAILED` ERROR record with the traceback for every unhandled
handler exception (uvicorn prints those to stdout only, which is lost once the
launching console is gone). Traceback capture verified red→green via
`test_unhandled_route_error_is_logged_with_traceback`. The WAL is now bounded
too — #238 landed: `PRAGMA wal_autocheckpoint=256` (≈1 MB, down from SQLite's
1000-page default) plus `Database.checkpoint_idle()`, run by the #148 janitor
every sweep via `asyncio.to_thread`: past a 4 MB soft threshold it attempts
`PRAGMA wal_checkpoint(TRUNCATE)` on a dedicated 1 s-busy_timeout connection
(busy readers surface as `busy=1`, as data rather than an exception), with a
documented 64 MB warning ceiling. Honest limit, probed by
`test_checkpoint_idle_survives_busy_readers`: a reader that pins the log
still blocks TRUNCATE — the mechanism bounds the WAL when checkpoints are
merely starved, and degrades to logged warnings (INFO on busy, WARNING past
the ceiling) if a pin never clears. Tests: `test_wal_autocheckpoint_is_bounded`,
`test_checkpoint_idle_*`, `test_janitor_checkpoints_idle_wal`,
`test_janitor_survives_a_failing_checkpoint`.

## Suspected causes (ranked, unverified)
1. One `sqlite3.Connection` per process shared across FastAPI threadpool workers
   (`check_same_thread=False`, no `threading.Lock`). Interleaved implicit BEGIN/COMMIT —
   `self._conn.execute(...)` in `artifacts.py`, `execution.py`, `memory.py`, `planning.py`,
   `projectnotes.py`, `references.py`, `roadmap.py`, `semantic.py` — can leave a
   transaction open, which holds the write lock.
2. Lazy cursor iteration while other threads write (`references.py:177`) keeps a read
   snapshot open → WAL can never be checkpointed (matches the 25 MB WAL).
3. Retry budget is only ~350 ms of backoff after a 15 s wait, and `execute()` itself is
   never retried — only `_commit()`.
4. Three+ writers on one file (server, worker, cli, evals) with no checkpoint policy
   (`wal_autocheckpoint` untouched, no explicit `wal_checkpoint`).

## Acceptance
- A repeatable stress harness that reproduces the lock red (concurrency ≥4 writers against
  a temp DB) — the diagnosing-bugs feedback loop. **Done (#223).**
- Single writer seam (connection-level lock or a write queue) so no two threads share an
  in-flight transaction. **Done (#223): per-thread connections, plus
  rollback-and-retry on both a failed statement and a failed COMMIT.**
- WAL bounded (autocheckpoint + explicit checkpoint on idle); documented ceiling.
  **Done (#238): wal_autocheckpoint=256, janitor-driven TRUNCATE past 4 MB,
  64 MB warning ceiling.**
- Server errors persisted to `logs/server.log`, not just stdout. **Done (#239).**


## R58 — Stale artifact expiry — dismiss orphaned choice/spec cards
**Status:** done

Pending `choice`/`spec` artifacts are never retired. `emit_choice_card` writes a row with `status='pending'` and the Artifacts tab + chat card render every non-answered row forever, so a card emitted by a run that was stopped, crashed, or simply ended unanswered reappears at every boot and accumulates (~7 found on the remote install, 2026-09-28 → 2026-10-10).

The answer path makes the dead ones harmless (`POST /artifacts/{id}/respond` only flips `status`), but there is no way to clear them from the UI other than picking a bogus option.

Fix:
- `status='dismissed'` as a distinct terminal state (not `answered` — no answer was given).
- `ArtifactStore.dismiss(id)`; `respond()` refuses a dismissed artifact so a stale card cannot be resurrected.
- `POST /artifacts/{id}/dismiss` endpoint + Dismiss button on pending cards (chat column and Artifacts tab).
- Dismissal is user-driven only — no automatic expiry, so a question the user has not read yet is never hidden behind their back.

Out of scope: anything that retires a card without the user asking.

## R59 — Dynamic dockable workspace (user-arrangeable panels)
**Status:** done

Every surface in the UI becomes a movable panel. Users drag tabs to split/merge/float, pop panels out to OS windows, save named presets, and the arrangement persists. Replaces the hard-coded five-zone flexbox shell (sidebar | explorer | editor | chat | bottom dock) with a docking layout engine.

Design: tech design #1. Implementation tracked as phased tickets (P0 refactor → P1 shell → P2 full catalogue → P3 persistence/palette → P4 polish).

**Progress.** P0 done (#226) — `App.jsx` 3288 → 1337 lines (historical: P0's count), panels/chrome/store extracted. P1 done (#236) — `dockview-react@8.6.1` (exact pin) renders five dockable panels (nav, explorer, editor, chat, diff) behind `?layout=dock`; the classic layout stays the default, so rollback is dropping the query flag. Preset geometry recorded by the gate (`tabs[<title>].width`): nav 256 / explorer 208 / chat 384 px, i.e. the requested 256/208/384, with the middle column taking the remainder (~652 px) — recorded, not asserted, because `pinSizes` redistributes the remainder per call. Monaco proven to reflow with its container in both directions (634 → 460 → 634 px) via `automaticLayout`; the hidden-then-revealed case is *not* covered, because dockview exposes no panel-level `setVisible` and ships no group action to click, so hiding a panel needs P3 UI. The new dependency costs **+98,152 B gzip / +420,269 B raw** in the main chunk (measured against a worktree build of `96fbb6e`), over tech design §5's ~60 KB cap — so `Workspace.jsx` is now `React.lazy` and the engine loads only under `?layout=dock` (its own 97,883 B gzip chunk), leaving the default path at +442 B gzip. See `code-design.md` §R59 P1. P2 done (#243) — all twenty catalogue panels registered in the dock shell; store-backed panels read from one visibility-gated `sessionData` store (2 s scheduler tick, `document.hidden` pause, per-topic error capture, mount-parity first fetch) instead of per-tab polls; a `+ Title` panel bar opens closed panels until the P3 palette lands; the smoke gate's dock walk now opens and checks all 20 panels (exit 0). Request budget (untracked `.scratch/probe_budget.py`, this session): four panels open = 15 `/api` requests per 10 s, down from 31 before every store panel was visibility-gated — dockview keeps background-tab panels mounted, measured, contrary to P1's unmount assumption. Known limits: Graph keeps a per-tab effect (its fetch keys on `activePath`, which a `(topic, session)` key cannot express); `/sessions/{id}/diff` takes ~14 s server-side on the long-lived dev session (measured in-browser), so the diff panel shows `loading…` for that long; the unhide path is store-unit-tested only. See `code-design.md` §R59 P2. P3 done (#244) — layout persistence (`layoutStore.ts`, `cd-layout-v1`, debounced 400 ms writes off `onDidLayoutChange`, defensive restore that strips unknown panels / falls back to the default preset with a surfaced notice on corrupt, future-version or empty saves), shipped presets (default/debug/review/watching as placements validated by tests), and a command palette (`Ctrl+Shift+P`/`Ctrl+K`: show/hide, move, float/dock, presets, save-as, reset) replacing the P2 panel bar; reload persistence, preset round-trip and the corrupt fallback are probed end-to-end (untracked `.scratch/p3_persistence_probe.py`, 9/9) and the dock gate opens all 20 panels *through the palette* (exit 0; since R64, Waterfall is opened via the sidebar's panel-list row instead, so the palette path is proven for 19 of the 20). Not drag-based: the reload proof mutates layout via the palette; dockview's drag internals were not re-proven. P4 done (#245) - popout windows (`api.addPopoutGroup` over `/popout.html`, palette "Pop out <panel> to a window" + `Dock <panel>` back, failure notice on a blocked popup; probed end-to-end in `.scratch/p4_popout_probe.py`, which also caught that `show:` would land new panels inside a popout when the active panel was popped out - fixed, under test) and the classic shell retired: `?layout=dock` flag, the classic flex layout, the sixteen-tab DockPanel and `panes.ts` (removed) are deleted; the catalogue keeps the classic geometry as `GEOMETRY`; the smoke gate runs the dock walk at the bare URL (20/20 panels, exit 0). Drag-to-popout not re-probed (palette path only); popout geometry, per-project layouts, density and tab-overflow menu remain unimplemented (phase-4 options). See `code-design.md` R59 P4.

## R60 — Written claims must be checkable: claim checker + measured bundle cost
**Status:** done

## Problem

Six consecutive commits (`38fbc89` → `666fded`) each carried a written claim the code did not support, and each was found by a reviewer *after* publication: an invented second banner shape, a "hide the editor" step that hid nothing, panel geometry the gate never recorded, `1439` lines against a measured `1488`, and two filenames that named something other than the real module (historical: they were `db.py` and `ast_tools.py`).

The mechanism is identical every time: the narrative is written from the diff, in the same pass as the change, so nothing can contradict it. `pytest`/`ruff`/`mypy` test the code, not the prose describing it, and the mandated review runs after the push — so the discovery point is structurally guaranteed to be late.

## What shipped

1. **`tools/claim_check.py`** — checks the mechanically settleable half: paths in backticks exist (resolving bare basenames against the tracked tree, root-level files, directory claims; gitignored build artefacts are skipped as unverifiable), `path:LINE` references point inside the file, short hex refs name a real commit, "N lines" next to a single named file matches, and backticked identifiers appear in tracked **source** — that last check runs on commit messages only, because documents legitimately name other people's APIs and planned ones. Explicit `(removed)`/`(historical)` markers let a document discuss a file it replaced. Deliberately not checked: test counts (that is `gates.bat`'s job) and anything phrased in prose.
2. **`tests/test_claim_check.py`** — 47 tests, each check exercised on a claim that must be caught *and* a near-identical one that must not, plus a parametrised test holding every living document (`STRICT_DOCS`) to zero unsupported claims. Red-verified twice: by breaking a real doc count, and by running the suite in a `git worktree` of HEAD, where the gitignored-path bug failed 4 of the 7 documents.
3. **The unverified half gets a rule, not a tool**, recorded in the `RESCUE.md` trap table: a claim about behaviour, measurement or absence carries its probe — the command and its output — or the word *unverified*.

## What it found immediately

The checker's own first sweep flagged a bare package filename in `code-design.md`, which led to the real defect behind it: the P1 bundle-cost claim (≈17.4 KB gzip) counted two of three dockview packages and omitted `dockview-core` (390,319 B raw / 90,074 B gzip). Measured properly against a worktree build of `96fbb6e`: the static import cost every user **+420,269 B raw / +98,152 B gzip** — 1.6× tech design #1 §5's ~60 KB cap — and §5's own instruction ("measure the built output before/after") had never been run. `Workspace.jsx` is now `React.lazy`, so the always-loaded entry moved **+880 B raw / +442 B gzip** and the engine's 97,883 B gzip chunk loads only under `?layout=dock`.

Also corrected by the sweep: a stale `App.jsx` size in `RESCUE.md` (~1488 → 1501), the `frontend/dist/` path, and the dockview typedef path.

## Consequences

- A stale count or renamed file in a living document now fails `pytest`, instead of waiting for a reviewer.
- The tool's first version produced 157 findings, almost all false (basenames resolved against the repo root only). Recorded in its docstring: a check that cries wolf is worse than no check.
- `gates.bat` now lints `tools/` along with `src` and `tests`, so the checker itself is held to the linter; the doc sweep rides on `pytest`.

## Not covered

Whether a mechanism works, whether a shape exists, and why an observation happened — five of the six original failures. Those need a probe, which no tool can supply.

## R61 — chrome-devtools-mcp as a standard default MCP server
**Status:** done

Add Google's chrome-devtools-mcp (Apache-2.0, npm `chrome-devtools-mcp`) as a seeded default MCP server so automated browser testing (screenshots, console, network, performance traces) is a standard capability. Spawn via npx with `--no-usage-statistics` and `--no-update-checks` (Google telemetry is on by default; opt out for a personal agent). Requires Chrome on the machine; absent npx means no entry, same as zai-vision (codegraph is gated on the codegraph binary instead).

Shipped (ticket #240): `chrome-devtools` entry in `_default_mcp_servers()` (`mcp_config.py`), seeded additively by `ensure_default_mcp` (user edits to an existing entry win; absent npx means no entry). Behaviour without Chrome on the machine: not yet verified (see code-design R61). NOTICE.md records the dependency (not vendored, so no Apache-2.0 redistribution obligation). Tests: `tests/test_mcp.py` seeding/skip tests.

## R62 — Claim gate: failure-mode prose must carry probe evidence
**Status:** done

Six consecutive commits shipped failure-mode claims a reviewer could not back ("silently returns 0", "can't miss a banner", "hides nothing"). The arithmetic half is gated by tools/claim_check.py; the failure-mode half is not. This closes it mechanically (ticket #241, shipped `f051ad5`, tightened after post-push review): a sentence in a commit message (or doc, on request) containing a failure-mode verb must carry a `[probe: ...]` annotation naming the command that demonstrated it, or state "not yet verified" — otherwise the check fails and the message is not committed. Default: on for --message-file, opt-in for documents (historical docs would scream). Honest limit: the checker is run by the agent as its documented pre-commit step, not wired into a git hook — a hook is a separate decision. Post-push review found and closed four holes (empty `[probe: ]`, a probe on a neighbouring bullet, `pecan never` matching `can never`, and the message-file default leaking onto documents in the same run); tests 43 → 47. Design notes: code-design.md §R62.

## R63 — Silent failure surfacing in dock panel mutations
**Status:** done

Pre-existing gaps logged during #234's review (ticket #242): Notes and
Standards swallowed mutation failures — Notes had five bare
`catch { /* transient */ }` blocks (keep-for-evals checkbox, add note, add
project note, resolve, delete) so a failed save silently discarded the user's
input or left optimistic UI lying; Standards had four unguarded mutations
(`saveDirectives`, `startEditSkill`, `saveSkill`) plus `deleteSkill`, which
removed the skill from the list regardless of the HTTP response.

Shipped (#242): every mutation catch surfaces through the same
`data-poll-error` Failure seam as the #234 loads — Notes via a `mutError`
line (which also reverts the checkbox and keeps the draft on failure);
Standards via an `errors.save` line (`saveSkill` failure keeps the editor
open so the body is not lost; `deleteSkill` checks `r.ok` before touching the
list). Failure rendering reuses the existing smoke-gate seam; the live-browser
failure path was not re-probed (the banner mechanism was probe-verified in
#234). Gates: vitest 117/117, build clean, eslint 0.

## R64 — Sidebar panel list — advertise every dock panel from the nav panel
**Status:** done

**Problem.** R59 P4 made the dock shell the only layout; the default preset mounts five panels and the other fifteen (Graph, Waterfall, Trace, Terminal, Processes, …) are reachable only through the command palette (Ctrl+K). Nothing on the default screen advertises that they exist — a user who does not know a panel exists cannot discover it.

**Fix.** The `nav` panel (Sidebar) gains a "Panels" section listing every catalogue panel except itself, each flagged open/closed from the live dockview api. Clicking a row shows an unknown panel through the same `runCommand('show:…')` path the palette uses (one source of truth for placement), and focuses an already-open one. Reactivity rides `onDidAddPanel`/`onDidRemovePanel`.

**Verification.** Pure seams under vitest/pytest (`panelListFor` derivation; verdict key for the new smoke probe), plus the dock smoke gate gains an end-to-end probe: click the Waterfall row in the sidebar and require the panel to render.

**Non-goals.** No hiding affordance per row (palette keeps that), no drag source from the sidebar, no reordering.

## R65 — discoverable, grabbable panel resize handles (sash affordance)
**Status:** done (#247) — the chat column was resizable all along; what was missing was any way to find or grab the handle. index.css: ±4px hit-area skirt for fine pointers (mirroring dockview's touch-only one), immediate hover highlight (`--dv-active-sash-transition-delay: 0s`), resting sash one step brighter than the border. Shell-wide: every splitter gains the affordance, no panel code changed. Guard: dock gate `_panel_resize` drags the chat sash from 5px OFF centre (outside the bare 4px element, inside the skirt) — red against the pre-fix bundle (384 → 384, exit 1), green after (384 → 504, exit 0); verdict tests cover pass/fail/absence and a source-parse pins the off-centre offset (a centred drag would pass with the CSS gone). Gates: vitest 175/175, eslint 0, build clean, pytest 875 passed/1 skipped, ruff/mypy clean, dock smoke exit 0. See `code-design.md` R65.

The user reports the chat "window" as not resizable. Probe (2026-10-26, .scratch/probe_chat_resize.py) shows the dockview sash drag DOES work — chat 384 → 280 → 480px, persisted across reload — but the sash is a 4px element, resting colour = --ss-border (invisible), hover highlight delayed 0.5s, and dockview ships hit-area expansion only for `pointer: coarse` (touch). With a mouse the handle is effectively ungrabbable, which reads as "not resizable".

Fix: index.css — ±4px transparent hit-area skirt on fine pointers, immediate hover highlight (--dv-active-sash-transition-delay: 0s), resting line one step brighter than the border. Guard: ui_smoke.py gains a chat-resize step that drags the sash from 5px OFF centre (outside the bare 4px element, inside the expanded hit area), so the gate goes red if the CSS regression returns.
