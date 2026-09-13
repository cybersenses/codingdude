# R5–R11 Implementation Plans

Decisions ratified with the user via the grilling loop (see Design Decisions #2–#15).
Sequencing: **R7-thin → R5-tracer → R11-tracer → R6-tracer → R9 → R8 → R10**,
one thin vertical slice per item per session; thickening passes get new tickets
after each tracer bullet closes.

---

## R7 — Session-replay eval harness (thin first)

**Design:** Recording = an export function over the already-persisted sessions
(messages) + trace events in SQLite → a JSON scenario file (`tests/scenarios/*.json`).
No new runtime recorder. Replay = the existing scripted-model infrastructure from
`bench.py` fed the recorded prompt sequence; assertions are Python predicates over
the resulting trace: gates ran before completion claims, questions asked before
irreversible steps, planning data updated, verification evidence cited.

**Tracer bullet (thin):** export + replay runner + 3–4 recorded scenarios; a
deliberately verification-skipping skill fails the suite.

**Thickening:** curated scenario library, CI promotion (local `make evals`-style
gate first — ratified: not CI initially), flake/cost hardening.

**Acceptance (thin):** `pytest` scenario suite green on current release; broken-skill
scenario fails with a readable assertion.

## R5 — Sandboxed prototype environments

**Design:** Native `sandbox.py` module (ratified: lifecycle is NOT driven via Docker
MCP; Docker MCP is added to `mcp_servers` config for ad-hoc use once Docker Desktop
is installed — pre-flight check from `90b882d` verifies availability).

- Agent tools: `sandbox_create`, `sandbox_exec`, `sandbox_teardown`, `sandbox_promote`.
- Tier 1 (tracer): **git worktree + ephemeral venv + seeded throwaway DB** — no Docker
  dependency; teardown guarantees byte-identical workdir.
- Tier 2 (thickening): container isolation when Docker is detected. Never silently
  degrade — every tool result states which tier it got.
- Preview: per-sandbox localhost port allocation, surfaced as a link in the session
  UI (no tunnels in v1; R1 vision loop covers screenshot verification).
- Promote: `sandbox_promote` diffs sandbox vs. its base commit and applies it to the
  real workdir **through the normal approval flow** — never a bypass.

**Tracer bullet:** Tier 1 create/exec/teardown + preview link + promote-via-approval;
e2e: two variants of a small feature, both clickable, teardown leaves workdir
byte-identical.

## R11 — Per-project reference knowledgebase

**Design:** Convention is the **existing `reference/` folder** (ratified — matches
the user's instinct; no migration). Files remain source of truth (human-editable,
git-versioned); a rebuildable **section-level index in the workdir-scoped SQLite**
carries chunks + the documented library version for staleness checks.

- Agent tools: `search_references` (indexed, cheap), `read_reference` (cite section).
- Ingest: user drops a file, or agent fetches a pinned URL ("pin the pydantic v2
  docs"); index built/refreshed automatically when files change.
- Freshness: reference version metadata vs. `pyproject.toml`/`package.json` pins →
  visible staleness warning tied to the pin.
- Skill guidance: relevant skills prompt to check references before trusting model
  memory.

**Tracer bullet:** folder + ingest + index + the two tools + pin-vs-version warning,
tested against the pydantic-ai tree already in `reference/`.

## R6 — Living-artifact collaboration channel

**Design:** New `artifacts` table + SSE events `ARTIFACT_EMITTED` / `ARTIFACT_UPDATED`
(ratified: not ephemeral — artifacts survive refresh and are linkable from planning
data). Agent tool `emit_artifact(kind, payload)`; user interactions flow back into
the agent's context next turn.

- MVP kinds: **choice cards** (pick auto-records a design decision with an artifact
  link) and **editable spec blocks** (edits are the agent's input next turn).
- Diagrams: render-only mermaid at first, no round-trip editing.

**Tracer bullet:** emit → render → interact → returns-to-context loop for choice
cards; spec blocks second pass within the item.

## R9 — Resumable long-horizon work

**Design:** Separate `ticket_execution` table keyed by ticket (ratified over columns
on `tickets` — preserves attempt lineage across sessions; rides R4's workdir-scoped
DB). Claims use **heartbeat** (worker touches claim each N s; stale after 2×N,
reclaimable) — an extension of R2's `/runs/{id}/alive` pattern. State per attempt:
claim owner, plan, step progress, per-step verification evidence. Agent's first move
on a claimed ticket = read resume state.

**Acceptance:** kill mid-ticket → new session resumes with no duplicated work and
evidence per completed step.

## R8 — Architecture guardrails

**Design:** **Soft-block** posture (ratified): linter findings never stop work, but
"done" requires fix-or-explicit-waiver; waivers are recorded as design decisions so
overrides are visible and auditable.

- Linter: seam violations, duplicated behaviors, boundary leaks — deep-module
  vocabulary from `codebase-design`; run before finishing a task.
- Contract-first codegen: approved domain model → typed interfaces + failing tests;
  deviation = explicit, visible contract change.
- ADR enforcement: contradicting a recorded decision surfaces the conflict; the user
  must explicitly overturn the ADR before proceeding.

## R10 — Cost and latency telemetry

**Design:** Atomic unit = **the model request** (ratified): provider-reported usage
already arrives per request (R3 snapshot — extend, don't duplicate). Tool-call wall
time recorded but not a billing unit; UI groups requests into a run timeline.
Prices: **config-driven** `models[].pricing` mirroring the `models.context_limit`
pattern; unknown models show tokens-only. Agent can query its own budget mid-run.

---

## Explicitly not building
- Driving the R5 sandbox lifecycle through Docker MCP (native module owns it).
- Public tunnel preview URLs in v1; promote paths that bypass approval.
- Ephemeral artifact transport; round-trip diagram editing in MVP.
- Hard CI gates for evals initially; hardcoded price tables.
