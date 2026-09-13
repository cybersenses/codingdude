# R5-tracer — Sandboxed prototype environments (tier 1: worktree+venv)

Tracer bullet for R5 (`docs/PLANS-R5-R11.md §R5`, ticket #1). No Docker needed.

## Reuse
- `worktrees.create_worktree` — isolation primitive (branch `codingdude/<name>`,
  dir `.codingdude-worktrees/<name>`). NOT reusing `build_worktree_toolset`
  closures (merge is a separate concern; promote is gated differently).
- `tools.scrubbed_env` — env hygiene for subprocesses (same as shell/git tools).
- Approval `policy.decide` + `_resolve_gate` pattern from `build_git_toolset`.

## Module: `src/codingdude/sandbox.py`
`build_sandbox_toolset(workdir, policy)` → `FunctionToolset` of 4 tools. Every
tool result states its tier (`tier=worktree+venv`) — never silent degradation.

- **sandbox_create(name)** → creates worktree via `create_worktree`, then an
  ephemeral venv at `.venv/` inside the sandbox (`uv venv` if available, else
  `python -m venv`). Allocates a free localhost port (ephemeral-socket probe)
  and reports `preview=http://localhost:<port>` (v1: link only; a dev server
  is started by the agent via `sandbox_exec`). Errors read like
  `error: worktree already exists: ...`.
- **sandbox_exec(name, command)** → runs the command with cwd = sandbox root
  and the sandbox venv's bin dir prepended to PATH. Gated like shell
  (`policy.decide`; NEEDS_GATE/DENIED → approval gate). Timeout 300s.
  Unknown sandbox → `error: no sandbox named <name>`.
- **sandbox_teardown(name)** → `git worktree remove --force` + `git worktree
  prune` + `git branch -D codingdude/<name>`. Guarantees the main workdir is
  byte-identical afterwards (everything lived under `.codingdude-worktrees/`
  + a branch); verifies with `git status --porcelain` being unchanged from
  pre-teardown and reports `workdir clean` in the result.
- **sandbox_promote(name, message)** → NEVER a bypass: gated via
  `policy.decide('git merge')` (always-gated, explicit consent), then merges
  `codingdude/<name>` into the main checkout (like `worktree_merge`), then
  tears the sandbox down. Reports exit + tier.

Tier detection is a report, not a fallback: tier 1 is the only tier in the
tracer; Docker detection (`shutil.which('docker')`) is included in the
result line (`docker=available|absent`) so thickening to tier 2 is observable.

## Tests — `tests/test_sandbox.py`
Seam: the FunctionToolset tools (same as `tests/test_worktrees.py`), real git
repo fixture, no mocks.

1. create → worktree + venv exist, result reports `tier=worktree+venv`,
   `preview=http://localhost:` port.
2. create twice → `error:` readable.
3. exec → writes a file inside the sandbox via the venv python; file lands in
   sandbox, NOT main workdir.
4. exec unknown name → readable error.
5. teardown → sandbox dir + branch gone; `git status --porcelain` of main
   unchanged (byte-identical guarantee); reports `workdir clean`.
6. promote → gated (policy without approval → gate message), and with an
   `--yolo`-style approving policy merges the sandbox change into main and
   tears down.

Verification: `uv run pytest -q tests/test_sandbox.py` then full
`uv run pytest -q` + ruff + mypy.
