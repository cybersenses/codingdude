# CodingDude — Product Requirements Document (PRD)

**Status:** living document · **Owner:** Cyberflex · **Hierarchy:** this PRD (why/what) → [TECH-DESIGN.md](TECH-DESIGN.md) (how) → [adr/](adr/) (decisions) → [specs/](specs/) (per-feature) → [ROADMAP.md](../ROADMAP.md) (execution)

---

## 1. Vision

CodingDude is a **personal, single-user coding agent**: an AI pair-programmer that
works inside your project directory, follows your conventions, asks before doing
anything risky, and proves its work with evidence. It runs locally, driven from a
web UI or headless CLI, against **any OpenAI-compatible or natively supported
LLM provider** the user chooses.

One sentence: *your own agent, your own models, your own machine, with human
approval in the loop.*

## 2. Target users

| Persona | Description | Primary need |
|---|---|---|
| **Personal developer (primary)** | A single developer running CodingDude on their own machine against their own projects | An agent they can trust with repo writes because every risky action is gated |
| **Power user / tinkerer** | Wants to pick models per slot, add custom providers, extend with MCP servers and skills | Full user-managed LLM configuration; no vendor lock-in |
| **OSS contributor** | Extending CodingDude itself (post-open-sourcing, R51) | Clear architecture, docs, ADRs, contribution path |
| **Commercial embedder** | Wants AGPL-exempt embedding/redistribution | Dual licence from Cyberflex |

**Explicitly not (yet) a target:** multi-tenant teams, hosted SaaS, anonymous
internet exposure. The server binds loopback, requires a login token, and
assumes one trusted user (see ADR-0004).

## 3. Problem statement

Generic hosted coding assistants: (a) hold your code and keys in someone else's
cloud, (b) can't be pointed at arbitrary model providers, (c) act on your repo
with coarse or no approval control, and (d) give no per-run evidence trail of
what they did. CodingDude exists to give the same agent capability with local
control, provider freedom, tiered approvals, and full traceability.

## 4. Product pillars

1. **Local-first & private** — engine, store, and UI run on the user's machine;
   nothing leaves except LLM API calls the user configured.
2. **Human in the loop** — gated actions (shell, git, edits, secrets-adjacent
   ops) require interactive Approval; Pattern Approval reduces friction without
   removing control; headless mode fails safe (exit 2) instead of guessing.
3. **Provider freedom** — any OpenAI-compatible endpoint or native provider,
   per-slot lineup (main/subagent/fallback/review/vision/extraction), runtime
   selection, key smoke tests. No hardcoded vendor.
4. **Evidence over assertion** — JSONL run traces, gates (tests/lint/types),
   review findings, coverage/mutation/benchmark tooling; the agent must prove
   work, not claim it.
5. **Process discipline** — planning mode (propose → approve → tracked steps →
   auto review), skills with progressive disclosure, directives, referential
   memory, onboarding convention discovery.
6. **Delegation & scale** — read-only subagents by default, isolated sandboxed
   delegation for risky work, MCP integration for external tools.

## 5. Feature inventory

### 5.1 Shipped (capabilities, not ticket lists)

- **Agent core:** pydantic-ai engine with failover; file/search/edit tools with
  AST-level operations (rename, references, CFG, impact, mutation tests,
  coverage, dead-code, benchmarks, API fuzzing); codegraph navigation;
  semantic search.
- **Trust & safety:** tiered approvals + pattern approvals; budget cap
  (survives `--yolo`); secret-scrubbed subprocess environments; security gate
  (Bandit/Semgrep/secret regexes) failing closed.
- **Session lifecycle:** persistent resumable sessions; context compaction;
  AGENT.md project context; DIRECTIVES.md; global/workdir memory with semantic
  retrieval and referential solutions (R49).
- **Process:** planning mode with auto step-completion review; delegation with
  briefs and sandbox exec; research pipeline; skills registry.
- **UI:** web server + per-run workers + SSE; React UI (chat, Diff, Files,
  Trace viewer, Renders, Memory, MCP, Config tabs); Monaco editor; interactive
  approval/plan/choice/spec/artifact cards.
- **Config:** user-defined providers (R50/#212), per-project `[models]`
  overrides, key verification, masked secrets.
- **Headless:** `codingdude run` with exit-code contract (0 ok / 2 gate /
  3 budget) for scripting.
- **Licensing (R51):** AGPL-3.0-or-later, CLA, trademark policy, dual licence.

### 5.2 Planned / open fronts (from ROADMAP open items)

- See [ROADMAP.md](../ROADMAP.md) — the roadmap is the single execution
  tracker; this PRD does not duplicate its backlog. New roadmap items must
  name the pillar (§4) they serve.

## 6. Non-goals

- Multi-user / team / org features, RBAC, shared sessions.
- Hosted SaaS or anonymous internet-facing deployment.
- Bundling a model or acting as a model provider.
- Being an IDE replacement — it complements the user's editor (the web UI is a
  *cockpit*, not an editor-first environment).
- Windows/macOS/Linux desktop packaging beyond distribution scripts (PyInstaller
  packaging is deferred, not promised).

## 7. Success metrics

- **Trust:** % of gated runs completed without user bypassing gates; zero
  incidents of ungated destructive action (security gate + tests as proxy).
- **Reliability:** edit-tool success rate; run-crash recovery rate (resume).
- **Evidence:** fraction of completed tickets citing gate output (tests run,
  exit codes) — enforceable via review automation.
- **Adoption (post-OSS):** contributors, stars, issues triaged, CLA-signed PRs.
- **Cost control:** per-run token/cost telemetry accuracy; budget-stop fidelity.

## 8. Constraints & dependencies

- Python 3.12+, uv, Windows-first (PowerShell/Git Bash) with cross-platform intent.
- pydantic-ai model interfaces; tree-sitter language packs; Playwright for
  visual gates; github-mcp-server.exe fetched from upstream releases (MIT,
  NOTICE.md).
- Legal: AGPL-3.0 obligations, CLA for contributions, trademark separation.

## 9. Document governance

- PRD changes = product decisions; discuss with the owner (Cyberflex) first.
- Architecture changes → new ADR; feature shapes → `specs/`; execution →
  ROADMAP tickets. Keep each level free of the others' content.
