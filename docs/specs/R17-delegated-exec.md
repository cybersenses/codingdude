# R17 — Write-capable delegation via the sandbox seam

Status: implemented (this commit). Phase 2 of the containerized-delegation path (C);
depends on R16 brief seams.

## Problem
Delegations are read-only, so a delegated agent can investigate but not
*try* anything: it cannot run the test suite, typecheck a hypothesis, or
apply and measure a candidate patch. That caps delegation usefulness at
"second opinion".

## Design
- `delegate(task, write=False)`. `write=True` adds exactly one tool to the
  subagent's read-only set: `exec_in_sandbox(command)` — backed by the
  existing sandbox tier (`sandbox_create` / `sandbox_exec` semantics,
  policy-gated like `sandbox_exec` already is). No default: write is an
  explicit per-call opt-in; config cannot enable it globally.
- The subagent never touches `sandbox_promote`. Effects cross the boundary
  only as a **diff**: when the delegation ends, the parent-side report
  includes `git diff` output from the sandbox tier; the parent presents it
  to the user — the human gate stays with the main session.
- Budget: `exec_in_sandbox` calls count against the same `max_requests`
  delegation budget (per-call subprocess timeout applies as today).
- Teardown: the sandbox tier is torn down after the report is extracted,
  same lifecycle discipline as R13 worktrees.

## Reused seams (no new infra)
- `codingdude.sandbox` create/exec/teardown
- `codingdude.tools.run_captured` for the parent-side diff extraction
- R16 `DelegationBrief` flows through unchanged; the report structure gains
  a `diff` section only when `write=True`.

## Contract
- `codingdude.tools.build_delegation_toolset` *(extended: `write` param)*
- `codingdude.sandbox.SandboxTier.exec` *(exec entry used by the bridge)*
