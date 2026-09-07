# Spec: CodingDude — personal coding agent

Status: ready-for-agent

## Problem Statement

As a developer, I want an agent I can hand real coding tasks to — explore a repo, make surgical edits, run the tests, commit and PR the result — but existing tools are either cloud services I don't control, terminal UIs that make reviewing changes and approving risky actions awkward, or toys that rewrite whole files and run commands without asking. I want it to use my own API keys (DeepSeek + GLM), keep history I can resume, remember things across sessions, and never touch anything outside the project I pointed it at without my explicit consent.

## Solution

CodingDude: a personal, single-user coding agent built on pydantic-ai with a browser UI. Each Session is bound to a Workdir (the project directory). The agent works through tools — search, read, surgical search/replace edits, shell (Git Bash by default), git, GitHub via `gh`, web search/fetch, MCP servers, and Delegation to read-only Subagents — under tiered Approval: reads and in-Workdir edits run free (every edit visible as a live diff), shell commands need Approval with Pattern Approval for the session, and remote mutations, outside-Workdir access, and deletions are always gated. The web UI shows the chat stream with a tool timeline, working-tree diff, file tree, terminal output, and cost meter; sessions persist in SQLite and resume with full context, auto-compacting when long. A Headless Run mode executes single tasks for scripting and fails safe on gated actions unless `--yolo` is passed. A cross-session Memory store (explicit remember/forget plus post-session extraction) and a per-project `AGENT.md` Project Context give it durable knowledge.

## User Stories

1. As a developer, I want to point a Session at any project directory and have it become the Workdir, so that all agent file operations stay inside that project.
2. As a developer, I want file tools to refuse any path outside the Workdir, so that a hallucinated path can't touch the rest of my machine.
3. As a developer, I want the agent to search file contents (grep-style) and find files by glob, so that it can navigate unfamiliar code without me curating context.
4. As a developer, I want the agent to read files and list directories on its own, so that exploration needs no Approval friction.
5. As a developer, I want edits applied as exact-match search/replace blocks with whole-file write only as fallback, so that changes are surgical, token-cheap, and fail loudly on stale content instead of silently corrupting files.
6. As a developer, I want every edit rendered as a colored diff in the UI as it happens, so that I can watch changes land without opening the files.
7. As a developer, I want new files and directories created through the same edit tooling, so that adding files is first-class.
8. As a developer, I want the shell tool to run commands through Git Bash by default (configurable per project), so that the agent uses the command idioms models know best.
9. As a developer, I want shell commands gated behind Approval, so that nothing executes on my machine unreviewed.
10. As a developer, I want Pattern Approval — approving `pytest` once covers every `pytest` invocation for the rest of the Session — so that the test loop isn't a click farm.
11. As a developer, I want remote mutations (`git push`, PRs), anything outside the Workdir, and file deletions to be always-gated regardless of patterns or `--yolo`-style relaxation, so that the truly destructive tier never silently loosens. *(Note: `--yolo` disables gates per ADR-0003 framing — the always-gated tier holds for pattern relaxation; `--yolo` is the explicit full-off switch.)*
12. As a developer, I want an Approval card inline in the chat with the exact command or action, its diff where applicable, and Approve / Approve-all-matching / Deny, so that deciding takes one glance.
13. As a developer, I want a `--yolo` flag for trusted work, so that long autonomous runs don't stop for me.
14. As a developer, I want the agent to run tests and builds via the gated shell and read their output, so that it can iterate until green.
15. As a developer, I want the main agent to Delegate tasks to Subagents on a cheap model (parallel spawns allowed), so that exploration and research don't burn flagship tokens or serialize.
16. As a developer, I want Subagents read-only by default and never holding Approval authority, so that Delegation can't be used to route around the gates.
17. As a developer, I want web search (DuckDuckGo, no key) and page fetch tools, so that the agent can check docs without leaving the loop.
18. As a developer, I want local git reads (status, log, diff) auto-approved, so that the agent understands repo state freely.
19. As a developer, I want commits and branch creation gated, so that repo history changes only when I say so.
20. As a developer, I want the full GitHub flow via `gh` — create PR, view checks/reviews — behind the always-gated tier, so that "make a PR for this" is one task.
21. As a developer, I want MCP servers attached from a global config merged with a per-project config (project wins), so that every project can share basics and add its own.
22. As a developer, I want the attached MCP tool list visible and manageable in the UI, so that I know what the agent can touch.
23. As a developer, I want Sessions persisted in SQLite and resumable from a sidebar, so that closing the browser never loses context.
24. As a developer, I want long Sessions auto-compacted at a token threshold using built-in compaction, with the compaction point visible in the timeline, so that context doesn't silently decay or explode.
25. As a developer, I want a per-Workdir `AGENT.md` Project Context auto-loaded each Session, so that durable project instructions ("use uv, never touch generated/") always apply.
26. As a developer, I want the agent to propose edits to `AGENT.md` that I approve, so that instructions evolve with the project under my control.
27. As a developer, I want a cross-session Memory store with explicit remember/forget tools, so that the agent banks preferences and project facts deliberately.
28. As a developer, I want automatic post-session extraction of missed facts into Memory, so that useful context survives without me managing it.
29. As a developer, I want Memory retrieved at Session start by keyword and recency, so that relevant facts arrive without an embeddings dependency (yet).
30. As a developer, I want Memory inspectable and deletable in the UI, global vs project-scoped, so that there is no hidden state.
31. As a developer, I want a live cost meter (tokens and dollars) per Session, so that spend is always visible.
32. As a developer, I want an optional hard-stop Budget Cap per Session (off by default, not bypassed by `--yolo`), so that a runaway loop can't burn credits.
33. As a developer, I want a Headless Run mode (`codingdude run "task"`) for scripting, so that I can drive the agent from terminals and CI.
34. As a developer, I want Headless Runs to abort with a report when they hit a gated action (unless `--yolo`), so that unattended never means unsupervised.
35. As a developer, I want the web UI layout: session sidebar, chat with inline tool-call timeline (args → output → duration, collapsible), right panel tabs for Diff / Files / Terminal / Cost, so that everything I approved in design is one glance away.
36. As a developer, I want runs executed in a per-run worker subprocess that streams events to the server, so that a wedged run dies alone and kill means cancel.
37. As a developer, I want the model lineup configurable (main `deepseek-v4-pro`, Subagents `deepseek-v4-flash`, failover `glm-5.3`), so that switching is three config values, not surgery.
38. As a developer, I want automatic failover to the fallback provider when the primary is down, so that provider outages don't kill Sessions.
39. As a developer, I want tool search over large toolsets (built-in capability) once MCP piles on tools, so that prompt cache and model attention survive scale.
40. As a developer, I want the server bound to localhost with a token, so that my agent and Workdirs aren't network-exposed.
41. As an automation author, I want headless output as a final report plus exit code reflecting success/gate-abort/failure, so that scripts can branch on the outcome.
42. As a developer, I want AST-level tools (find definition/references) in a later phase, so that navigation outgrows text grep.
43. As a developer, I want embeddings-based semantic code search and Memory retrieval in the final phase, so that relevance upgrades without re-architecting.

## Implementation Decisions

- **Engine**: a pydantic-ai Agent whose tools are composed toolsets (FunctionToolset for coding tools, MCPToolset from merged config, common web tools). One engine entry point: *start run (Session + prompt) → event stream → final state*. Both frontends (web worker, headless) drive the identical engine.
- **Models**: main `deepseek:deepseek-v4-pro`, Subagents `deepseek:deepseek-v4-flash`, wrapped in FallbackModel with `zai:glm-5.3`. All three are config values.
- **Approvals**: built-in `ApprovalRequiredToolset` semantics with deferred tool calls; a run pauses on a gated action until Approve / Approve-all-matching / Deny arrives. Tier table: auto (reads, searches, in-Workdir edits) / gated + Pattern Approval (shell) / always gated (remote mutations, outside-Workdir, deletions). `--yolo` disables gates explicitly; Budget Cap holds regardless.
- **Edits**: search/replace blocks as primary format, whole-file write as fallback for new/tiny files; the UI computes and displays diffs independent of edit format.
- **Execution model**: per ADR-0002, the server spawns one worker subprocess per run; workers connect back via local WebSocket, stream native agent events; the server bridges to browser SSE (AG-UI protocol via pydantic-ai's UI adapter layer) and persists messages to SQLite. Headless executes in-process.
- **Persistence**: single SQLite database under the user config directory; tables for sessions (keyed by Workdir), serialized message history, approvals, Memory entries, and usage/cost.
- **Compaction**: built-in compaction capabilities at a token threshold; compaction events surface in the timeline.
- **Memory**: explicit remember/forget tools plus a cheap-model post-session extraction pass; retrieval injects top-N entries (keyword + recency) at Session start; entries are global or Workdir-scoped.
- **Project Context**: `AGENT.md` at Workdir root auto-loaded; agent-proposed edits flow through Approval.
- **Delegation**: a single delegation tool spawning Subagents with a task description and read-only toolset on the cheap model; parallel spawns; results fold into parent context.
- **Git/GitHub**: local reads auto; commit/branch gated; push/PR via `gh` always gated.
- **MCP**: global config merged with per-project config (project wins) loaded via the built-in MCP config loader; toolset filtering and tool search apply as toolsets grow.
- **Web frontend**: React + Vite + Tailwind, custom components, AG-UI client over SSE (per ADR-0001).
- **Server**: FastAPI, localhost bind + token auth.
- **Shell tool**: Git Bash default, per-project configurable (PowerShell opt-in).
- **Headless**: engine + policy wrapper per ADR-0003; exit codes distinguish success / gate-abort / failure; `--yolo` opts into full autonomy.

## Testing Decisions

- **Good tests assert external behavior at the seams, never implementation details.** Two seams, per the agreed plan:
  - **Engine seam (deep)**: drive the single engine entry point with pydantic-ai `FunctionModel` (scripted model responses). Tools run for real against a temporary Workdir — real files, real search/replace, a real scratch git repo, a stubbed `gh`. Approval flows, edit formats, Memory, compaction, and Budget Cap are all observed here as event streams and filesystem/DB outcomes.
  - **HTTP seam (thin)**: FastAPI routes (session create/list/resume, run stream, approve/deny) via test client against the same scripted engine; the AG-UI event contract is asserted here and serves as the frontend's interface spec.
- No browser E2E in this spec; the React UI is covered by the AG-UI contract at the HTTP seam.
- Prior art: none in-repo (greenfield); pydantic-ai's `TestModel`/`FunctionModel` are the established mechanism this builds on.

## Out of Scope

- Durable execution (Temporal/DBOS/Prefect) — remains a stretch decision; Session resumption covers crash recovery for now.
- Multi-user support, remote/network exposure beyond localhost+token, authentication systems.
- Terminal UI (REPL/TUI) — dropped per ADR-0001; Headless Run is the only non-web entry point.
- Browser E2E test automation.
- Voice/realtime interfaces, mobile clients.
- An ML-based Approval policy engine — the tier table is static and user-configured.
- Packaging/distribution beyond local installation with uv.

## Further Notes

- Build phases (from the grilling session): (1) foundations + rename to `codingdude` + git init + schema + test harness; (2) core engine: tools, tiers, sessions, compaction, cost, headless, Project Context; (3) web UI + worker orchestration; (4) Delegation, Memory, web tools; (5) git/`gh` + MCP; (6) AST tools, embeddings, failover polish, durable-exec stretch decision.
- Glossary terms live in `CONTEXT.md` (Session, Workdir, Approval, Pattern Approval, Subagent, Delegation, Memory Entry, Project Context, Headless Run, Budget Cap); ADRs 0001–0003 record the frontend, execution-model, and headless-safety decisions.
- The `--yolo` vs always-gated interaction (story 11) resolved as: pattern relaxation never unlocks the always-gated tier; only the explicit `--yolo` flag does, and Budget Cap survives it.
