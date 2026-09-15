"""Git worktree isolation: run a session in an isolated worktree + branch so
parallel sessions on the same repo never collide, and experimental changes
merge back only when the user is satisfied.

Layout: `<repo>/.codingdude-worktrees/<name>/` with branch
`codingdude/<name>`. The main checkout is never touched until you merge.
"""

import subprocess
from pathlib import Path

from pydantic_ai.toolsets import FunctionToolset

from .tools import scrubbed_env

WORKTREE_DIRNAME = '.codingdude-worktrees'
BRANCH_PREFIX = 'codingdude/'


def _git(workdir: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ['git', *args], cwd=workdir, capture_output=True, text=True, check=check
    )
    return result.stdout.strip()


class WorktreeError(Exception):
    pass


def create_worktree(workdir: Path, name: str) -> Path:
    """Create `.codingdude-worktrees/<name>` worktree on branch
    `codingdude/<name>`. Fails cleanly when the repo has no commits (nothing
    to isolate yet) or the worktree already exists."""
    worktree_root = workdir / WORKTREE_DIRNAME
    worktree_path = worktree_root / name
    branch = f'{BRANCH_PREFIX}{name}'
    if worktree_path.exists():
        raise WorktreeError(f'worktree already exists: {worktree_path}')
    # `git worktree add` requires at least one commit on the repo
    probe = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=workdir, capture_output=True, text=True
    )
    if probe.returncode != 0:
        raise WorktreeError(
            'the repository has no commits yet — make an initial commit first'
        )
    _git(workdir, 'worktree', 'add', '-b', branch, str(worktree_path))
    return worktree_path


def remove_worktree(workdir: Path, name: str) -> None:
    """Force-remove `.codingdude-worktrees/<name>` and its branch. Delegation
    teardown (R13): safe on absent paths, never raises."""
    path = workdir / WORKTREE_DIRNAME / name
    if path.exists():
        _git(workdir, 'worktree', 'remove', '--force', str(path), check=False)
        _git(workdir, 'worktree', 'prune', check=False)
    _git(workdir, 'branch', '-D', f'{BRANCH_PREFIX}{name}', check=False)


def build_worktree_toolset(workdir: Path, approvals=None) -> FunctionToolset:
    """`worktree_create` / `worktree_list` / `worktree_merge`: the isolation
    lifecycle. merge runs `git merge` in the MAIN checkout — gated like other
    mutations of the main tree."""

    async def worktree_create(name: str) -> str:
        try:
            path = create_worktree(workdir, name)
        except WorktreeError as exc:
            return f'error: {exc}'
        return f'worktree ready: {path} (branch codingdude/{name})'

    async def worktree_list() -> str:
        result = subprocess.run(
            ['git', 'worktree', 'list', '--porcelain'],
            cwd=workdir, capture_output=True, text=True
        )
        out = []
        for block in result.stdout.split('\n\n'):
            for line in block.splitlines():
                if line.startswith('worktree '):
                    out.append(line.removeprefix('worktree '))
        return '\n'.join(out) or '(none)'

    async def worktree_merge(name: str) -> str:
        """Merge `codingdude/<name>` into the current branch of the main
        checkout (gated like other main-tree mutations)."""
        import asyncio

        if approvals is not None:
            from .approvals import DENIED, NEEDS_GATE
            from .tools import _resolve_gate

            command = f'git merge codingdude/{name}'
            decision = approvals.decide(command)
            if decision in (NEEDS_GATE, DENIED):
                await _resolve_gate(approvals, command, always=decision == DENIED)
        proc = await asyncio.create_subprocess_exec(
            'git', 'merge', f'codingdude/{name}', '--no-edit',
            cwd=workdir, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=scrubbed_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError:
            proc.kill()
            return 'merge timed out'
        out = (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()
        code = proc.returncode if proc.returncode is not None else -1
        summary = f'exit {code}\n{out}' if out else f'exit {code}'
        return summary

    return FunctionToolset([worktree_create, worktree_merge, worktree_list])
