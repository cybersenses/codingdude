# Design: Uber Agent — software-engineering intelligence for CodingDude

Status: draft for discussion (seed for the next grilling round — not yet approved)

## Problem

CodingDude today is a capable *hands*: it can edit, run, test, commit, and browse code. But it has no engineering *judgment* layered on top:

- It doesn't know **your standards** (naming, test policy, framework choices) unless they happen to be in AGENT.md.
- It has no **reusable procedures** — every session re-derives "how we do TDD here" from scratch.
- It has no **plan/execute separation** — it wing-walks straight into edits instead of designing first.
- It has no **review loop** — nothing checks its work against the standards before declaring done.

The uber-agent goal: encode software-engineering knowledge in four composable layers, and give the agent a planning discipline that uses them.

## The four knowledge layers

### 1. Directives — always-on rules (the "constitution")

Rules that apply to *every* run, no retrieval step. Injected into the system instruction each run, with precedence:

```
base engine instructions
  ← global directives      ~/.codingdude/DIRECTIVES.md     (user-level taste)
  ← project directives     <workdir>/AGENT.md              (exists already)
```

- Format: plain markdown, sections over JSON — models follow prose rules well.
- Budget-capped (e.g. first 4000 chars) with a `directives_full` warning marker so silent truncation is impossible.
- Edits route through the approval gate like AGENT.md.
- Enforcement is *soft* (model reads them) + *hard* where cheap: a **review checklist** derived from directives that the review pass (layer 4) checks mechanically.

### 2. Skills — on-demand procedures (the "playbooks")

Port the SKILL.md convention you already use: a directory of skills, each with `name`, `description` (the trigger), and a body (the procedure).

- **Progressive disclosure**: only the index (name + one-line description) is always in context — cheap. A `load_skill(name)` tool fetches the body when the agent recognizes the situation. This is the same mechanism ZCode/Claude Code use, and it's why 20+ skills don't blow the context.
- Sources, merged project-over-global: `~/.codingdude/skills/*/SKILL.md`, `<workdir>/.codingdude/skills/*/SKILL.md`.
- Seed set to ship with: `tdd`, `code-review`, `debugging`, `refactoring`, `git-hygiene`, `domain-modeling` — the procedures we've been following manually in this very project.
- Skills are **advisory**: the agent decides to load one; the user can pin one ("use TDD for this task") which force-loads it into instructions.

### 3. Planning — design before code

The biggest behavioral upgrade. A **plan/execute split** for any non-trivial task:

1. **Plan phase**: the agent researches (read-only tools only) and produces a structured plan — Pydantic model: goal, design steps (numbered, each with rationale), files-to-touch, risks, test seams. Rendered as a **plan card** in the UI.
2. **Approval**: plan cards reuse the approval-card machinery — Approve / Edit (send changes back) / Reject.
3. **Execute phase**: plan steps become a tracked checklist via a `todo` tool (write_status(step, state)); the UI shows progress against the approved plan. Deviations require re-approval (or are allowed under `--yolo`).
4. Small tasks bypass planning via a size heuristic (or explicit "just do it").

This is Claude-Code's plan mode generalized, and it's where "design steps" live: the plan *is* the design document, persisted in the session and reviewable later.

### 4. Review — the second pair of eyes

Before declaring done (on plan completion, or on demand):

- A **review subagent** (the existing delegation machinery, read-only) receives: the diff, the plan, and the directive checklist.
- It reports findings as structured output: violations, risks, test gaps — rendered as a **review card**; the main agent must address or explicitly justify each.
- Cheap-model first pass; escalate to the main model only when findings exist.

## Architecture on top of what exists

Everything composes with machinery already built — no new subsystem types:

| Piece | Built on | New code |
|---|---|---|
| Directive injection | instructions assembly in `Engine.run` (already composes AGENT.md + memory) | ~1 module |
| Skill registry + `load_skill` | `FunctionToolset` + file scanning (like memory) | ~1 module |
| Plan model + approval | approval cards (GATE flow) + structured output | plan tool + UI card |
| Todo tracking | tool + events (like EditChange) | tool + event |
| Review subagent | delegation tool (exists) with structured output | prompt + schema |

The injection point for layers 1–2 is a **DirectiveCapability**: pydantic-ai's `ProcessHistory`/`ReinjectSystemPrompt` hooks re-assert instructions on long runs (fighting context drift during compaction) — free from the framework.

## Build order (proposed tickets)

- **18 — Directives**: global DIRECTIVES.md + injection + budget cap + approval-gated edits. (Small, immediate payoff.)
- **19 — Skill registry**: scan/merge, index-in-context, `load_skill` tool, seed skills. (Small.)
- **20 — Planning mode**: plan model, plan card UI, todo tracking, plan/execute split. (The big one — worth its own grilling round on the plan schema and bypass rules.)
- **21 — Review loop**: review subagent + directive checklist + review card. (Depends on 18 for the checklist.)
- **22 — Evals**: a small benchmark of gold tasks (per skill) so behavior changes are measurable, not vibes.

## Out of scope / explicit non-goals

- Multi-agent debates/committees — expensive, hard to steer, low yield vs a disciplined plan-review loop.
- Fine-tuning — directives + skills + review achieve steering without training.
- Auto-updating standards from git history — seductive, unreliable; keep standards human-authored.
