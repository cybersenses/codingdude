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
**Status:** open

Adopt behavioral techniques (not personas) from agency-agents Engineering Division: (a) Minimal Change Engineer scope discipline into surgical-patch; (b) three-level explanation + inspection-coverage honesty into caveman-explore.

## R41 — R41 — Persona checklist distillation + specialty-actions seam
**Status:** open

Strip the idea-value from all agency-agents personas (~130, 23 divisions) into versioned reference checklists per specialty, indexed via search_references. Later: a specialty-actions seam so users can invoke these as actions on the systems CodingDude builds. Explicitly NOT adopting personas as identity.

## R42 — R42 — Human code comprehension (user-facing views of generated code)
**Status:** open

Second feature thrust: tools that help a HUMAN understand the code the agent generates — call graphs, structure views, dependency maps of the produced code itself (not run telemetry). Audience shift: agent introspection (R31/R35/R38) stays, but new work must derive from user value.
