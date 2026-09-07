# CodingDude

CodingDude is a personal, single-user coding agent built on pydantic-ai, driven from a web UI, that works on a Workdir with tiered human Approval for risky actions.

## Language

**Session**:
A continuous conversation between the user and the agent within one project, persisted and resumable after close.
_Avoid_: Chat, conversation, run

**Workdir**:
The project directory a session operates in; file tools refuse paths outside it.
_Avoid_: Workspace, project root, repo

**Approval**:
Explicit user consent required before the agent executes a gated action. Granted per action, or per pattern for the rest of a session.
_Avoid_: Permission, confirmation, gate

**Pattern Approval**:
A session-scoped approval covering all future actions matching a pattern (e.g. all `pytest` invocations).
_Avoid_: Allowlist, whitelist

**Subagent**:
A child agent spawned by the main agent for a delegated task, with its own restricted toolset, reporting back to its parent.
_Avoid_: Worker, delegate, minion

**Memory Entry**:
A durable fact banked across sessions, scoped globally or to a Workdir, retrievable at session start.
_Avoid_: Note, preference (when meaning a stored fact), knowledge

**Project Context**:
The `AGENT.md` file at a Workdir root holding durable user-authored instructions, auto-loaded every session.
_Avoid_: README, instructions file, system prompt

**Headless Run**:
A non-interactive single-task execution without the web UI; gated actions abort it unless `--yolo` is passed.
_Avoid_: CLI mode, batch mode

**Delegation**:
The act of a subagent being spawned for a task; subagents are read-only by default and never hold approval authority.
_Avoid_: Dispatch, handoff

**Budget Cap**:
An optional per-session spending limit; exceeding it hard-stops the run. Off by default, not bypassed by `--yolo`.
_Avoid_: Limit, quota
