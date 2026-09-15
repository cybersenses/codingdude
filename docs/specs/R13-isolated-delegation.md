# R13 — Isolated delegated agents

Status: implemented (this commit). Roadmap decision #9.

## What shipped
- `delegate(task)` runs the subagent's read-only toolset against a **fresh git
  worktree** (`.codingdude-worktrees/delegation-<hex>`), torn down when the
  delegation returns. If the worktree cannot be created (no commits, name
  clash), delegation falls back to the main workdir and says so.
- Trace events: `DELEGATION_STARTED` (`task`, `isolated`) and
  `DELEGATION_COMPLETED` (`requests`, tokens, `cost_usd`, `isolated`) via the
  run tracer — delegation is visible in the trace JSONL and the UI.
- Budget ceiling: config `[delegation] max_requests` (default 40) enforced via
  `UsageLimits`; exceeding it returns a readable tool result ("delegation
  aborted: exceeded …") instead of a stack trace.
- Cost attribution: the delegation's usage is billed to the parent session
  (`record_usage`), same as other auxiliary model calls (H6).

## Deliberate deviations from the roadmap scope
1. **Container tier for risky tasks: deferred.** The delegated agent runs
   in-process (pydantic-ai); pointing its tools at a container mount path
   would read the host's mount point, not the container. Container isolation
   only becomes meaningful when delegations can execute code (R5 sandbox exec
   inside delegation). Recorded here so the deferral is a decision, not an
   oversight.
2. **Merge via `sandbox_promote`: not applicable.** Subagents are read-only,
   so there is nothing to merge; the worktree is discarded, not promoted.
3. **`DELEGATION_PROGRESS` live streaming: deferred.** pydantic-ai exposes no
   per-request hook for a nested `Agent.run` without streaming plumbing; the
   STARTED/COMPLETED pair brackets the delegation honestly today.

## Contract
- `codingdude.config.DelegationConfig`
- `codingdude.worktrees.remove_worktree`
- `codingdude.tools.build_delegation_toolset`
- `codingdude.codegraph_boot.refresh_codegraph_index` *(R14 shared slice)*
