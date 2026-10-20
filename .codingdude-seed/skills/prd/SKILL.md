{"name": "prd", "description": "Use when starting a new product, epic, or feature that needs a product requirements document - before roadmap items, tickets, or specs. Also when the user says 'write a PRD', 'what are the requirements', or requirements feel vague or contested.", "triggers": ["write a prd", "product requirements", "requirements doc", "define the product", "what are we building"]}

# PRD — Product Requirements Document

A PRD answers **WHAT and WHY** — never HOW. It is the parent artifact: roadmap items trace to its requirements, tech designs implement them, tickets deliver them. Store it with `create_prd` (DB-backed, visible in the Planning UI); update with `update_prd`, never by rewriting a file.

## Positioning

| Artifact | Question | Tool |
| --- | --- | --- |
| PRD (this skill) | What & why | `create_prd` / `update_prd` |
| Tech design (`tech-design` skill) | How | `create_tech_design` |
| Roadmap item / ticket | When & in what order | `create_roadmap_item` / `create_ticket` |
| ADR (`record_decision`) | One hard, irreversible trade-off | `record_decision` |

`to-spec` synthesizes implementation specs for one feature; a PRD covers a whole product/epic and outlives any single spec.

## Process

1. **Gather, don't invent.** Use the conversation and codebase (`grilling` for gaps). The user owns goals and priorities; the codebase answers feasibility questions — ask it, not the user.
2. **Number every requirement** `REQ-<n>` — traceability depends on it. One requirement = one testable behavior.
3. **Write with `create_prd`** using the skeleton below. Non-goals are mandatory: an unbounded PRD is a wish list.
4. **Surface open questions** in their own section — never bury them in prose.
5. Set status `active` (via `update_prd`) once the user confirms the goals/metrics; `sunset` when the product area retires.
6. **Feed downstream:** each roadmap item's body cites the REQ ids it delivers; `create_tech_design` takes the PRD's id.

## Skeleton

```markdown
## Problem
The user's pain, in the user's words. No implementation.

## Users & Actors
Who this is for; who administers it.

## Goals
3–5 measurable outcomes.

## Non-Goals
Explicitly out of scope. (Mandatory — this is what keeps the PRD honest.)

## Requirements
REQ-1 <one testable behavior>
REQ-2 ... (each requirement: user-visible, atomic, verifiable)

## Success Metrics
How we'll know it worked, with numbers where possible.

## Open Questions
- Q1 ... (each blocking REQs it touches)
```

## It's working if

- Every requirement has a REQ id and reads as testable behavior, not a solution.
- Non-Goals and Open Questions are populated, not boilerplate.
- The PRD lives in the Planning data (`list_planning` shows it), not an orphan file.
- Downstream artifacts cite REQ ids: roadmap bodies, tech-design traceability, tickets.

## Common mistakes

- **Solution leakage** — "REQ-3: use Redis" is a design decision, not a requirement. Move it to `tech-design`; record the trade-off via `record_decision`.
- **Mega-PRD** — one PRD per product or epic; split when requirements exceed ~15.
- **Silent edits** — `update_prd` with a full body clobbers; `read_prd` first, merge, then write.
