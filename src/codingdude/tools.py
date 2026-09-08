"""Coding tools: list, read, grep, glob, plus surgical edits — all confined to the Workdir."""

import re
from collections.abc import Callable
from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from .approvals import DENIED, NEEDS_GATE
from .directives import project_directives_guard
from .errors import GateRequired
from .events import EditChange

MAX_READ_BYTES = 256 * 1024
MAX_GREP_RESULTS = 50
MAX_FILE_BYTES = 2 * 1024 * 1024  # grep: skip files larger than this
SKIP_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache'}
SECRET_MARKERS = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')


def scrubbed_env() -> dict:
    """Child-process environment with secret-looking variables removed.

    The shell tool must not hand provider keys to arbitrary commands. Windows
    system vars (SYSTEMROOT etc.) are preserved so networking still works.
    """
    import os

    return {
        k: v
        for k, v in os.environ.items()
        if not any(marker in k.upper() for marker in SECRET_MARKERS) or k in ('SYSTEMROOT',)
    }

EditEmitter = Callable[[EditChange], None]


def build_toolset(
    workdir: Path,
    on_edit: EditEmitter | None = None,
    read_only: bool = False,
    approvals=None,
) -> FunctionToolset:
    """Build the toolset bound to a Workdir (via closure). read_only strips edits.

    `approvals` (an ApprovalPolicy) gates AGENT.md edits — the Project Context
    changes only with explicit consent (spec story 26).
    """

    def resolve(path: str) -> Path:
        target = (workdir / path).resolve()
        try:
            target.relative_to(workdir)
        except ValueError:
            raise ModelRetry(
                f'Path {path!r} is outside the Workdir. '
                'Only paths inside the Workdir are accessible.'
            ) from None
        return target

    def list_dir(path: str = '.') -> str:
        entries = sorted(
            resolve(path).iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
        return '\n'.join(
            f"{'d' if e.is_dir() else '-'} {e.name}" for e in entries
        ) or '(empty)'

    def read_file(path: str) -> str:
        target = resolve(path)
        if not target.is_file():
            raise ModelRetry(f'{path!r} is not a file (list_dir first to explore).')
        return target.read_text(encoding='utf-8', errors='replace')[:MAX_READ_BYTES]

    def grep(pattern: str, path: str = '.') -> str:
        target = resolve(path)
        rx = re.compile(pattern)
        results: list[str] = []
        files = [target] if target.is_file() else sorted(target.rglob('*'))
        for f in files:
            if not f.is_file() or any(
                part in SKIP_DIRS for part in f.relative_to(workdir).parts
            ):
                continue
            try:
                data = f.read_text(encoding='utf-8', errors='replace')[:MAX_FILE_BYTES]
                for i, line in enumerate(data.splitlines(), 1):
                    if rx.search(line):
                        results.append(f'{f.relative_to(workdir)}:{i}: {line.strip()}')
                        if len(results) >= MAX_GREP_RESULTS:
                            return '\n'.join(results) + '\n(truncated)'
            except OSError:
                continue
        return '\n'.join(results) or '(no matches)'

    def glob(pattern: str) -> str:
        matches = sorted(
            str(m.relative_to(workdir)) for m in workdir.glob(pattern) if m.is_file()
        )
        return '\n'.join(matches) or '(no matches)'

    def emit_edit(path: str, before: str, after: str) -> None:
        if on_edit:
            on_edit(EditChange(kind='edit', path=path, before=before, after=after))

    def _guard_project_context(path: str) -> None:
        """Directives files (AGENT.md, DIRECTIVES.md) always need a gate."""
        if not project_directives_guard(path):
            return
        if approvals is None:
            raise ModelRetry(
                f'{path} is a directives file; editing it requires the approval '
                'system, which is not active in this run.'
            )
        if not approvals.yolo:
            raise GateRequired(f'edit {path}')

    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Replace `old_text` with `new_text` — the match must be unique."""
        _guard_project_context(path)
        target = resolve(path)
        before = target.read_text(encoding='utf-8', errors='replace')
        count = before.count(old_text)
        if count == 0:
            raise ModelRetry(
                f'old_text not found in {path}. Re-read the file and copy the '
                'exact text to replace, including whitespace.'
            )
        if count > 1:
            raise ModelRetry(
                f'old_text appears more than once in {path} ({count} times). '
                'Include more surrounding context so the match is unique.'
            )
        after = before.replace(old_text, new_text, 1)
        target.write_text(after, encoding='utf-8')
        emit_edit(path, before, after)
        return f'edited {path}'

    def write_file(path: str, content: str) -> str:
        """Create a new file (with parent dirs). Existing non-empty files must use edit_file."""
        _guard_project_context(path)
        target = resolve(path)
        existed = target.read_text(encoding='utf-8', errors='replace') if target.exists() else ''
        if existed.strip():
            raise ModelRetry(
                f'{path} already exists and is not empty — use edit_file to change it.'
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        emit_edit(path, existed, content)
        return f'wrote {path}'

    tools: list[Callable] = [list_dir, read_file, grep, glob]
    if not read_only:
        tools += [edit_file, write_file]
    return FunctionToolset(tools)


async def _resolve_gate(policy, command: str, always: bool = False) -> None:
    """Resolve a gated action: ask the user (interactive) or abort (headless).

    - no ask callback → GateRequired (headless abort, ADR-0003)
    - 'approve' → run once
    - 'pattern' → approve for the session; on always-gated actions the pattern
      is never persisted (only this one run goes through)
    - 'deny' → ModelRetry so the model knows the user said no
    """
    if policy is None or policy.ask is None:
        raise GateRequired(command)
    answer = await policy.ask(command)
    if answer == 'deny':
        raise ModelRetry(
            f'User DENIED this action: {command}. Do not retry it unchanged; '
            'continue the task another way or ask the user what to do instead.'
        )
    if answer == 'pattern' and not always:
        pattern = command.strip().split()[0]
        policy.approve_pattern(pattern)
        if policy.on_pattern:
            policy.on_pattern(pattern)


def build_shell_toolset(workdir: Path, policy, shell_bin: str = 'bash') -> FunctionToolset:
    """The shell tool, gated by the ApprovalPolicy."""

    async def shell(command: str, timeout: int = 120) -> str:
        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=decision == DENIED)
        import asyncio

        if shell_bin == 'powershell':
            argv = ['powershell', '-NoProfile', '-Command', command]
        else:
            argv = ['bash', '-c', command]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=scrubbed_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return 'exit code: -1 (timed out)'
        output = (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()
        if len(output) > 8000:
            output = output[:4000] + '\n...\n' + output[-4000:]
        return f'exit code: {proc.returncode}\n{output}'

    return FunctionToolset([shell])


def build_delegation_toolset(workdir: Path, subagent_model) -> FunctionToolset:
    """The `delegate` tool: spawn a read-only Subagent on the cheap model.

    Subagents never see edit/write/shell/delegation tools, so Delegation
    can't route around Approval tiers.
    """

    async def delegate(task: str) -> str:
        from pydantic_ai import Agent

        from .prompts import load_prompt

        sub_agent: Agent = Agent(
            model=subagent_model,
            instructions=load_prompt('delegation'),
            toolsets=[build_toolset(workdir, read_only=True)],
        )
        result = await sub_agent.run(task)
        return str(result.output)

    return FunctionToolset([delegate])


def build_web_toolset() -> 'AbstractToolset':
    """Web search (DuckDuckGo, no key) and page fetch, from pydantic-ai's built-ins.

    Local URLs are allowed — tests and self-hosted docs are legitimate targets.
    """
    from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
    from pydantic_ai.common_tools.web_fetch import web_fetch_tool
    from pydantic_ai.toolsets import RenamedToolset

    inner = FunctionToolset(
        [duckduckgo_search_tool(), web_fetch_tool(allow_local_urls=True)]
    )
    return RenamedToolset(inner, {'web_search': 'duckduckgo_search'})


def build_git_toolset(workdir: Path, policy) -> FunctionToolset:
    """Git/GitHub tools under the tier table: reads auto, commit/branch gated,
    push/PR always-gated (never pattern-unlockable)."""

    async def _run(argv: list[str], timeout: int = 60, use_shell: bool = False) -> str:
        import asyncio

        if use_shell:
            # Windows resolves gh (and test stubs) through the shell's PATH.
            proc = await asyncio.create_subprocess_shell(
                ' '.join(argv), cwd=workdir, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=scrubbed_env(),
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=workdir, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=scrubbed_env(),
            )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()
        code = proc.returncode if proc.returncode is not None else -1
        return f'exit {code}\n{out}' if out else f'exit {code}'

    async def git_status() -> str:
        return await _run(['git', 'status', '--porcelain', '-b'])

    async def git_log(limit: int = 20) -> str:
        return await _run(['git', 'log', '--oneline', f'-n{limit}'])

    async def git_diff(path: str = '') -> str:
        argv = ['git', 'diff']
        if path:
            argv += ['--', path]
        return await _run(argv)

    async def _gate(command: str, always: bool = False) -> None:
        from .approvals import DENIED, NEEDS_GATE

        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=always or decision == DENIED)

    async def git_commit(message: str) -> str:
        await _gate('git commit')
        await _run(['git', 'add', '-A'])
        out = await _run(['git', 'commit', '-m', message])
        if 'commit failed' in out or 'exit 1' in out:
            return f'commit failed: {out}'
        return f'committed: {out.split(chr(10))[0]}'

    async def git_branch(name: str) -> str:
        await _gate('git branch')
        return await _run(['git', 'checkout', '-b', name])

    async def git_push(remote: str = 'origin', branch: str = 'main') -> str:
        await _gate('git push', always=True)  # always-gated: only explicit consent
        return await _run(['git', 'push', remote, branch])

    async def gh_pr_create(title: str, body: str) -> str:
        await _gate('gh pr create', always=True)
        # shell=True so Windows resolves gh (and test stubs) via PATH
        return await _run(
            ['gh', 'pr', 'create', '--title', title, '--body', body, '--fill'],
            use_shell=True,
        )

    async def gh_pr_view(number: int) -> str:
        await _gate('gh pr view', always=True)
        return await _run(['gh', 'pr', 'view', str(number)], use_shell=True)

    return FunctionToolset(
        [git_status, git_log, git_diff, git_commit, git_branch, git_push, gh_pr_create, gh_pr_view]
    )


def resolve_workdir_path(workdir: str | Path, path: str) -> tuple[Path | None, str | None]:
    """Containment-checked path resolution for server-side file access.

    Returns (path, None) or (None, error). Symlink-safe: both sides are
    resolved before the containment check.
    """
    root = Path(workdir).resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None, f'path {path!r} escapes the Workdir'
    return target, None




def build_coverage_toolset(workdir: Path, policy) -> FunctionToolset:
    """The `run_coverage` tool: execute the project's test suite with coverage
    analysis and return per-file results with missing lines. Gated like shell
    (it runs your tests), pattern-approvable under 'coverage'."""

    async def run_coverage(source: str = '.') -> str:
        from .approvals import NEEDS_GATE

        command = f'python -m pytest --cov={source} --cov-report=term-missing -q'
        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=decision == DENIED)
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            'bash', '-c', command,
            cwd=workdir, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=scrubbed_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        except TimeoutError:
            proc.kill()
            return 'exit code: -1 (coverage run timed out after 600s)'
        out = (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()
        if len(out) > 6000:
            out = out[:3000] + '\n...\n' + out[-3000:]
        return f'exit code: {proc.returncode}\n{out}'

    return FunctionToolset([run_coverage])
