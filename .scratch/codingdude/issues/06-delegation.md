# 06: Delegation

**What to build:** The main agent can spawn Subagents. One delegation tool takes a task description, spawns a Subagent on the cheap model (`deepseek-v4-flash`) with a read-only toolset, runs spawns in parallel, and folds results back into the parent's context. Subagents never hold Approval authority and never write.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** resolved

- [x] A scripted main-agent run delegates an exploration task and uses the Subagent's findings in its final answer
- [x] The Subagent runs on the configured cheap model, not the main model
- [x] The Subagent's toolset contains no write/shell tools — attempts aren't available to call
- [x] Two parallel delegations complete and both results reach the parent
- [x] A Subagent encountering a would-be-gated action surfaces it to the parent rather than pausing or executing *(realized as: Subagents have no shell tool at all — there is nothing to gate)*

## Comments

2026-09-07: Commit d96fb51. `delegate(task)` builds a fresh read-only Agent per call (glob/grep/list_dir/read_file only — enforced by build_toolset(read_only=True), so a task demanding write tools still can't get them). Parallel spawns work via pydantic-ai's parallel tool execution (both results returned). Subagent model comes from config `models.subagent`; if that provider isn't configured, delegation is disabled with a warning rather than failing runs.
