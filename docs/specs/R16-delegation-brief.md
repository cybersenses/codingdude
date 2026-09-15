# R16 — Delegation task briefs

Status: implemented (this commit). Phase 1 of the containerized-delegation
path (C); Phase 2 is R17.

## Problem
`delegate(task)` ships a bare task string to the subagent. The subagent
re-derives context the parent already has: which files matter, which symbols,
which spec contract governs the work. Every delegation pays that rediscovery
cost in model requests — the delegation's scarcest resource (max_requests).

## What ships
- `codingdude.delegation.DelegationBrief` — dataclass: `task`, `symbols`
  (identifier-like tokens from the task that verifiably exist in the
  workdir), `contract` (a `## Contract` section from `docs/specs/*.md` that
  mentions a verified symbol, with its source path), `budget`.
- `codingdude.delegation.build_brief(task, workdir, budget)` — pure-ish
  builder; bounded scan (SKIP_DIRS respected, file count and size capped,
  early exit per symbol). No symbols found → empty brief, prompt is the bare
  task (no noise sections).
- `codingdude.delegation.brief_prompt(brief)` — the subagent run input:
  task verbatim, then optional `Delegation brief:` context (symbols,
  contract excerpt).
- `delegate()` builds the brief before spawning and runs the subagent on
  `brief_prompt(brief)`. Trace: STARTED/COMPLETED events now carry a shared
  `delegation_id` so a delegation pair is linkable in the trace JSONL.

## Deliberate scope cuts
- No `done_conditions` field: no caller supplies one yet — add when a
  consumer exists.
- Symbol mining is local scan + existence check, not codegraph queries:
  codegraph is an MCP server, not an in-process library. Existence-verified
  tokens give the same briefing value with zero infra.

## Contract
- `codingdude.delegation.DelegationBrief`
- `codingdude.delegation.build_brief`
- `codingdude.delegation.brief_prompt`
