"""Coding tools: list, read, grep, glob, plus surgical edits — all confined to the Workdir."""

import re
from pathlib import Path
from typing import Callable

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from .approvals import DENIED, NEEDS_GATE
from .events import EditChange

MAX_READ_BYTES = 256 * 1024
MAX_GREP_RESULTS = 50
SKIP_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache'}

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
                for i, line in enumerate(
                    f.read_text(encoding='utf-8', errors='replace').splitlines(), 1
                ):
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
        """AGENT.md is the user's Project Context — edits always need a gate."""
        if Path(path).name.lower() != 'agent.md':
            return
        if approvals is None:
            raise ModelRetry(
                f'{path} is the Project Context; editing it requires the approval '
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


class GateRequired(Exception):
    """A shell command needs Approval; the run pauses/aborts per ADR-0003."""

    def __init__(self, command: str):
        self.command = command
        super().__init__(f'gate required for: {command}')


def build_shell_toolset(workdir: Path, policy, shell_bin: str = 'bash') -> FunctionToolset:
    """The shell tool, gated by the ApprovalPolicy."""

    def shell(command: str, timeout: int = 120) -> str:
        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            # Both pause/abort the run per ADR-0003; the difference is that a
            # DENIED (always-gated) command can never be pattern-approved.
            raise GateRequired(command)
        import subprocess

        if shell_bin == 'powershell':
            argv = ['powershell', '-NoProfile', '-Command', command]
        else:
            argv = ['bash', '-c', command]
        result = subprocess.run(
            argv, cwd=workdir, capture_output=True, text=True, timeout=timeout
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 8000:
            output = output[:4000] + '\n...\n' + output[-4000:]
        return f'exit code: {result.returncode}\n{output}'

    return FunctionToolset([shell])


def build_delegation_toolset(workdir: Path, subagent_model) -> FunctionToolset:
    """The `delegate` tool: spawn a read-only Subagent on the cheap model.

    Subagents never see edit/write/shell/delegation tools, so Delegation
    can't route around Approval tiers.
    """

    async def delegate(task: str) -> str:
        from pydantic_ai import Agent

        sub_agent: Agent = Agent(
            model=subagent_model,
            instructions=(
                'You are a CodingDude Subagent doing read-only research for the '
                'main agent. Investigate the task with the file tools and answer '
                'with your findings, concisely.'
            ),
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

    def _run(argv: list[str], timeout: int = 60, use_shell: bool = False) -> str:
        import subprocess

        result = subprocess.run(
            argv, cwd=workdir, capture_output=True, text=True, timeout=timeout,
            shell=use_shell,
        )
        out = (result.stdout + result.stderr).strip()
        return f'exit {result.returncode}\n{out}' if out else f'exit {result.returncode}'

    def git_status() -> str:
        return _run(['git', 'status', '--porcelain', '-b'])

    def git_log(limit: int = 20) -> str:
        return _run(['git', 'log', '--oneline', f'-n{limit}'])

    def git_diff(path: str = '') -> str:
        argv = ['git', 'diff']
        if path:
            argv += ['--', path]
        return _run(argv)

    def _gate(command: str) -> None:
        from .approvals import DENIED, NEEDS_GATE

        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            raise GateRequired(command)

    def git_commit(message: str) -> str:
        _gate('git commit')
        import subprocess

        subprocess.run(['git', 'add', '-A'], cwd=workdir, capture_output=True, text=True)
        result = subprocess.run(
            ['git', 'commit', '-m', message], cwd=workdir, capture_output=True, text=True
        )
        detail = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            return f'commit failed: {detail}'
        return f'committed: {detail}'

    def git_branch(name: str) -> str:
        _gate('git branch')
        return _run(['git', 'checkout', '-b', name])

    def git_push(remote: str = 'origin', branch: str = 'main') -> str:
        _gate('git push')  # always-gated: only yolo unlocks
        return _run(['git', 'push', remote, branch])

    def gh_pr_create(title: str, body: str) -> str:
        _gate('gh pr create')  # always-gated: only yolo unlocks
        # shell=True so Windows resolves gh (and test stubs) via PATH
        return _run(
            ['gh', 'pr', 'create', '--title', title, '--body', body, '--fill'],
            use_shell=True,
        )

    def gh_pr_view(number: int) -> str:
        _gate('gh pr view')  # always-gated: only yolo unlocks
        return _run(['gh', 'pr', 'view', str(number)], use_shell=True)

    return FunctionToolset(
        [git_status, git_log, git_diff, git_commit, git_branch, git_push, gh_pr_create, gh_pr_view]
    )
