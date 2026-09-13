"""R5 sandboxed prototype environments — tier 1: git worktree + ephemeral venv.

Every tool result states its tier (`tier=worktree+venv`) and whether Docker
was detected, so thickening to tier 2 (containers) is never a silent degrade.
Promotion into the real workdir is gated through the normal approval flow —
never a bypass (see docs/specs/R5-tracer-sandbox.md).
"""

import asyncio
import os
import shutil
import socket
import subprocess
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from .tools import _resolve_gate, scrubbed_env
from .worktrees import BRANCH_PREFIX, WORKTREE_DIRNAME, WorktreeError, create_worktree

EXEC_TIMEOUT = 300


def _git(workdir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['git', *args], cwd=workdir, capture_output=True,
                          text=True, env=scrubbed_env())


def docker_available() -> bool:
    return shutil.which('docker') is not None


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


def _tier_line() -> str:
    return (f'tier=worktree+venv docker='
            f'{"available" if docker_available() else "absent"}')


async def _run(argv: list[str], cwd: Path, timeout: int) -> str:
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=scrubbed_env())
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return f'exit -1\n command timed out after {timeout}s'
    out = (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()
    code = proc.returncode if proc.returncode is not None else -1
    return f'exit {code}\n{out}' if out else f'exit {code}'


def build_sandbox_toolset(workdir: Path, policy) -> FunctionToolset:
    """sandbox_create / sandbox_exec / sandbox_teardown / sandbox_promote:
    the tier-1 prototype lifecycle on top of git worktrees."""

    def sandbox_path(name: str) -> Path:
        return workdir / WORKTREE_DIRNAME / name

    async def sandbox_create(name: str) -> str:
        try:
            sandbox = create_worktree(workdir, name)
        except WorktreeError as exc:
            return f'error: {exc}'
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
        sandbox = sandbox_path(name)
        if not sandbox.exists():
            return f'error: no sandbox named {name} — create it first'
        from .approvals import DENIED, NEEDS_GATE

        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=decision == DENIED)
        env_bin = _venv_bin(sandbox)
        env = scrubbed_env()
        path_key = next((k for k in env if k.lower() == 'path'), 'PATH')
        env[path_key] = f'{env_bin}{os.pathsep}{env.get(path_key, "")}'
        proc = await asyncio.create_subprocess_shell(
            command, cwd=sandbox, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), EXEC_TIMEOUT)
        except TimeoutError:
            proc.kill()
            return f'exit -1\n command timed out after {EXEC_TIMEOUT}s'
        out = (stdout.decode(errors='replace')
               + stderr.decode(errors='replace')).strip()
        code = proc.returncode if proc.returncode is not None else -1
        summary = f'exit {code}\n{out}' if out else f'exit {code}'
        return f'{summary} {_tier_line()}'

    async def sandbox_teardown(name: str) -> str:
        sandbox = sandbox_path(name)
        if not sandbox.exists():
            return f'error: no sandbox named {name} — nothing to tear down'
        before = _status(workdir)
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

