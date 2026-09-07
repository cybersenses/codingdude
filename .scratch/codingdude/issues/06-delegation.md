# 06: Delegation

**What to build:** The main agent can spawn Subagents. One delegation tool takes a task description, spawns a Subagent on the cheap model (`deepseek-v4-flash`) with a read-only toolset, runs spawns in parallel, and folds results back into the parent's context. Subagents never hold Approval authority and never write.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** ready-for-agent

- [ ] A scripted main-agent run delegates an exploration task and uses the Subagent's findings in its final answer
- [ ] The Subagent runs on the configured cheap model, not the main model
- [ ] The Subagent's toolset contains no write/shell tools — attempts aren't available to call
- [ ] Two parallel delegations complete and both results reach the parent
- [ ] A Subagent encountering a would-be-gated action surfaces it to the parent rather than pausing or executing
