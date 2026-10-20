{"name": "tech-design", "description": "Use when a non-trivial feature or system needs a technical design document before implementation - architecture, data/API contracts, alternatives, risks. Also when the user says 'write a TDD', 'design doc', 'how should we build this', or before creating tickets for architecturally significant work.", "triggers": ["tech design", "design doc", "technical design document", "architecture decision", "how should we build", "write a tdd"]}

# Tech Design — the HOW document

A technical design document (TDD) answers **HOW** a system meets its requirements. It stays separate from the PRD (WHAT/WHY) and from ADRs (single irreversible decisions): the TDD links to both. Store it with `create_tech_design` (DB-backed, Planning UI); link it to its PRD with `prd_id` — traceability is the point.

## Positioning

| Artifact | Question | Where |
| --- | --- | --- |
| PRD (`prd` skill) | What & why | `create_prd` |
| Tech design (this skill) | How, whole-system | `create_tech_design` |
| ADR (`record_decision`) | One hard trade-off | `record_decision` |

Hard, surprising, irreversible trade-offs inside a design get their own `record_decision` entry; the TDD references it. Everything else (context, contracts, alternatives) lives in the TDD.

## Process

1. **Start from requirements.** `read_prd` for the PRD this implements; if none exists and the work is a product feature, write one first (`prd` skill). Pure infrastructure may skip the PRD.
2. **Read the codebase before designing** — name the exact modules and seams you'll touch (reuse `codebase-design` vocabulary). A design that ignores existing structure is fiction.
3. **Write with `create_tech_design`**, `prd_id` set, using the skeleton below.
4. **Trace every requirement**: each REQ-<n> maps to named design elements. Unmappable requirement = design gap; untraced design element = gold-plating.
5. **Alternatives are the most valuable section.** At least two real alternatives, why the chosen one wins, and what it costs.
6. Status lifecycle (`update_tech_design`): `draft` → `approved` once the user signs off → `superseded` when replaced. **Never rewrite an approved design** — create a successor and mark the old one `superseded`.
7. **Feed downstream:** tickets created from the design cite its id; each `record_decision` during implementation links back.

## Skeleton

```markdown
## Context
The problem, the constraints, the codebase reality (named modules/seams).

## Requirements Traceability
| REQ | Design element(s) |
| REQ-1 | <component/module/interface> |

## Architecture
Components, responsibilities, data flow. Diagrams welcome.

## Data & API Contracts
Schemas, endpoints, invariants — precise enough to code against.

## Alternatives Considered
1. <option> — rejected because <cost/risk>.
2. <chosen> — wins on <criteria>, costs <trade-off>.

## Risks & Mitigations
- Risk → mitigation (each concrete, not "test carefully").
```

## It's working if

- Every REQ from the PRD appears in the traceability table, and every design element traces back.
- Alternatives name at least two real options with costs, not straw men.
- Irreversible trade-offs also exist as `record_decision` entries the TDD references.
- The doc lives in Planning data (`list_planning`), linked via `prd_id`, and approved designs are never silently rewritten.

## Common mistakes

- **Restating the PRD** — requirements belong in the table as ids, not prose copies.
- **No alternatives** — a design with one option is a decision without thinking; the alternatives section is where design actually happens.
- **File paths and snippets as design** — code rots fast; design names modules and contracts, implementation lives in the repo.
- **Editing approved designs in place** — supersede instead, so history shows what was believed when.
