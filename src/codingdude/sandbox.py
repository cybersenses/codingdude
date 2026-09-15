"""R5 sandboxed prototype environments — tier 1: git worktree + ephemeral venv.

Every tool result states its tier (`tier=worktree+venv`) and whether Docker
was detected, so thickening to tier 2 (containers) is never a silent degrade.
Promotion into the real workdir is gated through the normal approval flow —
never a bypass (see docs/specs/R5-tracer-sandbox.md).
"""

import os
import shutil
import socket
import subprocess
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from .tools import _resolve_gate, run_captured, scrubbed_env
from .worktrees import BRANCH_PREFIX, WORKTREE_DIRNAME, WorktreeError, create_worktree

EXEC_TIMEOUT = 300


def _git(workdir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['git', *args], cwd=workdir, capture_output=True,
                          text=True, env=scrubbed_env())


def docker_cli() -> str | None:
    """Resolve a usable docker CLI ('docker', or 'docker.exe' from WSL)."""
    for name in ('docker', 'docker.exe'):
        path = shutil.which(name)
        if path is not None:
            return path
    return None


def docker_usable() -> bool:
    """CLI present AND daemon answering — a broken daemon must not be chosen."""
    cli = docker_cli()
    if cli is None:
        return False
    proc = subprocess.run(
        [cli, 'version', '--format', '{{.Server.Version}}'],
        capture_output=True, text=True, env=scrubbed_env(), timeout=30)
    return proc.returncode == 0


def container_image_ready(image: str) -> bool:
    """True when the image is available locally or can be pulled."""
    if not docker_usable():
        return False
    cli = docker_cli()
    assert cli is not None  # docker_usable() proved the CLI exists
    ok = subprocess.run([cli, 'image', 'inspect', image],
                        capture_output=True, text=True,
                        env=scrubbed_env()).returncode == 0
    if ok:
        return True
    pull = subprocess.run([cli, 'pull', image], capture_output=True, text=True,
                          env=scrubbed_env())
    return pull.returncode == 0


def free_port() -> int:
    """A free localhost port for the sandbox preview (no tunnels in v1)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _make_venv(sandbox: Path) -> tuple[bool, str]:
    """Create `<sandbox>/.venv` — uv when available (fast), else stdlib venv.
    Returns (ok, detail)."""
    uv = shutil.which('uv')
    if uv is not None:
        proc = subprocess.run([uv, 'venv', str(sandbox / '.venv')],
                              capture_output=True, text=True, env=scrubbed_env())
        if proc.returncode == 0:
            return True, 'uv venv'
        detail = proc.stderr.strip() or proc.stdout.strip()
    else:
        detail = ''
    proc = subprocess.run(
        ['python', '-m', 'venv', str(sandbox / '.venv')],
        capture_output=True, text=True, env=scrubbed_env())
    if proc.returncode == 0:
        return True, 'python -m venv'
    detail = proc.stderr.strip() or proc.stdout.strip() or detail
    return False, detail


def _venv_bin(sandbox: Path) -> Path:
    venv_bin = sandbox / '.venv' / (
        'Scripts' if (sandbox / '.venv' / 'Scripts').exists() else 'bin')
    return venv_bin


def _status(workdir: Path) -> str:
    """git status excluding the sandboxes' own dir — teardown may legitimately
    remove it (git drops the untracked-dir entry once it is empty)."""
    lines = _git(workdir, 'status', '--porcelain').stdout.splitlines()
    return '\n'.join(line for line in lines if not line.endswith(WORKTREE_DIRNAME + '/'))


def _tier_line(tier: str = 'worktree+venv', image: str | None = None) -> str:
    if tier == 'container':
        return f'tier=container image={image} docker=available'
    return (f'tier=worktree+venv docker='
            f'{"available" if docker_usable() else "absent"}')


CONTAINER_IMAGE = 'python:3.12-alpine'
CONTAINER_PREFIX = 'codingdude-sb-'
CONTAINER_MOUNT = '/workspace'


async def _run(argv: list[str], cwd: Path, timeout: int) -> str:
    cap = await run_captured(argv, cwd=cwd, timeout=timeout)
    if cap is None:
        return f'exit -1\n command timed out after {timeout}s'
    return f'exit {cap.code}\n{cap.combined}' if cap.combined else f'exit {cap.code}'


async def container_running(container: str) -> bool:
    proc = subprocess.run(
        [docker_cli() or 'docker', 'inspect', '-f',
         '{{.State.Running}}', container],
        capture_output=True, text=True, env=scrubbed_env())
    return proc.returncode == 0 and 'true' in proc.stdout


async def exec_in_sandbox_dir(
    workdir: Path, name: str, command: str, policy=None,
) -> str:
    """Run a command inside sandbox `name` (R17 shared core: the sandbox_exec
    tool and write-capable delegations use this one implementation)."""
    sandbox = workdir / WORKTREE_DIRNAME / name
    if not sandbox.exists():
        return f'error: no sandbox named {name} - create it first'
    from .approvals import DENIED, NEEDS_GATE
    from .tools import _resolve_gate

    if policy is not None:
        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=decision == DENIED)
    container = CONTAINER_PREFIX + name
    if await container_running(container):
        summary = await _run([
            docker_cli() or 'docker', 'exec', '-w', CONTAINER_MOUNT,
            container, 'sh', '-c', command], sandbox, EXEC_TIMEOUT)
        return f'{summary} {_tier_line("container", CONTAINER_IMAGE)}'
    env_bin = _venv_bin(sandbox)
    env = scrubbed_env()
    path_key = next((k for k in env if k.lower() == 'path'), 'PATH')
    env[path_key] = f'{env_bin}{os.pathsep}{env.get(path_key, "")}'
    cap = await run_captured([command], cwd=sandbox, timeout=EXEC_TIMEOUT,
                             env=env, shell=True)
    if cap is None:
        return f'exit -1\n command timed out after {EXEC_TIMEOUT}s'
    summary = f'exit {cap.code}\n{cap.combined}' if cap.combined else f'exit {cap.code}'
    return f'{summary} {_tier_line()}'


def build_sandbox_toolset(workdir: Path, policy) -> FunctionToolset:
    """sandbox_create / sandbox_exec / sandbox_teardown / sandbox_promote:
    the tier-1 prototype lifecycle on top of git worktrees."""

    def sandbox_path(name: str) -> Path:
        return workdir / WORKTREE_DIRNAME / name

    async def _container_running(container: str) -> bool:
        return await container_running(container)

    async def sandbox_create(name: str, tier: str = '') -> str:
        if tier not in ('', 'worktree', 'container'):
            return (f"error: unknown tier {tier!r} — use 'worktree' or "
                    "'container'")
        want_container = tier == 'container' or (
            tier == '' and docker_usable())
        if want_container and not docker_usable():
            if tier == 'container':
                return ('error: docker requested but not available — no '
                        'sandbox created')
            want_container = False  # default tier: fall back, report it
        try:
            sandbox = create_worktree(workdir, name)
        except WorktreeError as exc:
            return f'error: {exc}'
        if want_container:
            container = CONTAINER_PREFIX + name
            # Deterministic names: a stale container must not block reuse.
            subprocess.run(
                [docker_cli() or 'docker', 'rm', '-f', container],
                capture_output=True, text=True, env=scrubbed_env())
            port = free_port()
            run = await _run([
                docker_cli() or 'docker', 'run', '-d', '--name', container,
                '-v', f'{sandbox}:{CONTAINER_MOUNT}', '-w', CONTAINER_MOUNT,
                '-p', f'{port}:8000', CONTAINER_IMAGE, 'sleep', 'infinity'],
                workdir, 120)
            if not run.startswith('exit 0'):
                _git(workdir, 'worktree', 'remove', '--force', str(sandbox))
                _git(workdir, 'worktree', 'prune')
                return f'error: container start failed: {run}'
            return (f'sandbox ready: {sandbox} (branch {BRANCH_PREFIX}{name}, '
                    f'container {container}) preview=http://localhost:{port} '
                    f'{_tier_line("container", CONTAINER_IMAGE)}')
        ok, detail = _make_venv(sandbox)
        if not ok:
            # Fail fast: a sandbox without a venv is not a sandbox; remove the
            # half-built worktree so the name stays reusable.
            _git(workdir, 'worktree', 'remove', '--force', str(sandbox))
            _git(workdir, 'worktree', 'prune')
            return f'error: venv creation failed: {detail}'
        port = free_port()
        return (f'sandbox ready: {sandbox} (branch {BRANCH_PREFIX}{name}) '
                f'preview=http://localhost:{port} venv={detail} {_tier_line()}')

    async def sandbox_exec(name: str, command: str) -> str:
        return await exec_in_sandbox_dir(workdir, name, command, policy)

    async def sandbox_teardown(name: str) -> str:
        sandbox = sandbox_path(name)
        if not sandbox.exists():
            return f'error: no sandbox named {name} — nothing to tear down'
        before = _status(workdir)
        # Container tier: remove the container first (ignore absent).
        subprocess.run(
            [docker_cli() or 'docker', 'rm', '-f', CONTAINER_PREFIX + name],
            capture_output=True, text=True, env=scrubbed_env())
        _git(workdir, 'worktree', 'remove', '--force', str(sandbox))
        _git(workdir, 'worktree', 'prune')
        _git(workdir, 'branch', '-D', f'{BRANCH_PREFIX}{name}')
        after = _status(workdir)
        clean = 'workdir clean' if after == before else 'workdir CHANGED'
        return f'sandbox {name} torn down; {clean} {_tier_line()}'

    async def sandbox_promote(name: str, message: str) -> str:
        """Merge the sandbox branch into the main checkout — always gated:
        promotion touches the real workdir, so it needs explicit consent."""
        sandbox = sandbox_path(name)
        if not sandbox.exists():
            return f'error: no sandbox named {name} — nothing to promote'
        # Always gated: promotion touches the real workdir — explicit consent,
        # never pattern-unlockable (mirrors git push). yolo bypasses the gate
        # (ADR-0003 full-off switch), nothing else does.
        from .approvals import DENIED, NEEDS_GATE

        decision = policy.decide('git merge')
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, 'git merge', always=decision == DENIED)
        merge = await _run(
            ['git', 'merge', f'{BRANCH_PREFIX}{name}', '--no-edit'], workdir, 120)
        if not merge.startswith('exit 0'):
            return f'error: merge failed: {merge}'
        teardown = await sandbox_teardown(name)
        return f'promoted {name}: {message}; {teardown}'

    return FunctionToolset([sandbox_create, sandbox_exec, sandbox_teardown,
                            sandbox_promote])

