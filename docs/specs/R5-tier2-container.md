# R5-thicken — Sandbox tier 2: container tier

Extends `src/codingdude/sandbox.py` (tier 1 shipped, commit `b3ceefd`) with a
Docker-backed sandbox tier. Precondition met: Docker Desktop verified working
(`docker.exe run --rm hello-world` passed in-session).

## Reuse
- `create_worktree` — isolation stays git-worktree-based; the container mounts
  the worktree. Teardown = container rm + tier-1 teardown.
- `scrubbed_env`, `_resolve_gate`, `free_port`, `_tier_line` — unchanged.
- Docker is driven via **CLI subprocess** (`docker` or `docker.exe` on PATH),
  not docker-py — deterministic teardown, same pattern as `_git`.

## Tier selection — explicit, never silent
`sandbox_create(name, tier='')` where tier ∈ `'' | 'worktree' | 'container'`:
- `''` (default): container when Docker is usable, else worktree+venv. The
  result line reports which tier actually ran.
- `'container'`: Docker unavailable → **error** (`docker requested but not
  available`), never a silent fallback.
- `'worktree'`: always tier 1.

Docker usable = a docker CLI resolves (`docker`, then `docker.exe`) AND
`docker version` exits 0 (CLI-present-but-broken daemon must not be chosen).

## Container tier behavior
- Worktree created as in tier 1, bind-mounted at `/workspace` in a
  `python:3.12-alpine` container named `codingdude-sb-<name>` (repo tag is a
  parameter with this default; tests skip if the image is unavailable).
- No venv is created (container is the runtime); result reports
  `tier=container image=python:3.12-alpine`.
- `preview=http://localhost:<port>` maps host port → container `8000`
  (`-p <port>:8000`).
- `sandbox_exec`: `docker exec -w /workspace codingdude-sb-<name> sh -c
  <command>`; same gating, timeout, and output framing as tier 1.
- `sandbox_teardown`: `docker rm -f` the container (ignore absent), then the
  tier-1 teardown — workdir-clean guarantee unchanged.
- `sandbox_promote`: unchanged (git merge from main workdir); works for both
  tiers.

## Tests — extend `tests/test_sandbox.py`
Seam unchanged: the FunctionToolset tools, real git repo, no mocks.
Container tests are guarded: `pytest.mark.skipif` when Docker is unusable or
the `python:3.12-alpine` image cannot be pulled.

1. `create(tier='worktree')` → tier-1 result even when Docker exists (explicit
   tier wins).
2. `create(tier='container')` → worktree + running container; result contains
   `tier=container`; exec `echo` inside the container sees `/workspace`.
3. `create(tier='container')` twice → readable error.
4. exec in container sandbox runs in `/workspace` (touches a file, file lands
   in the worktree on the host).
5. teardown container sandbox → container gone, worktree+branch gone,
   `workdir clean`.
6. `tier=''` on a machine without Docker → worktree tier reported (cover via
   monkeypatched `docker_usable → False`, no Docker needed).
7. `tier='container'` with `docker_usable → False` → readable error, no
   sandbox left behind.

Verification: `uv run pytest -q tests/test_sandbox.py` then full
`uv run pytest -q` + ruff + mypy.
