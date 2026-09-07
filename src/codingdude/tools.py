"""Coding tools: list, read, grep, glob, plus surgical edits — all confined to the Workdir."""

import re
from pathlib import Path
from typing import Callable

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from .approvals import DENIED, NEEDS_GATE
from .events import EditChange

MAX_READ_BYTES = 256 * 1024
MAX_GREP_RESULTS = 50
SKIP_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache'}

EditEmitter = Callable[[EditChange], None]


def build_toolset(
    workdir: Path, on_edit: EditEmitter | None = None, read_only: bool = False
) -> FunctionToolset:
    """Build the toolset bound to a Workdir (via closure). read_only strips edits."""

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

    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Replace `old_text` with `new_text` — the match must be unique."""
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
        target = resolve(path)
        if target.exists() and target.read_text(encoding='utf-8', errors='replace').strip():
            raise ModelRetry(
                f'{path} already exists and is not empty — use edit_file to change it.'
            )
        existed = target.read_text(encoding='utf-8', errors='replace') if target.exists() else ''
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
        if decision == NEEDS_GATE:
            raise GateRequired(command)
        if decision == DENIED:
            raise ModelRetry(
                f'Command refused: {command!r} is in the always-gated tier (remote '
                'mutations and destructive operations). It can only run with '
                'explicit user consent (yolo mode).'
            )
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


def build_web_toolset() -> FunctionToolset:
    """Web search (DuckDuckGo, no key) and page fetch, from pydantic-ai's built-ins.

    Local URLs are allowed — tests and self-hosted docs are legitimate targets.
    """
    from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
    from pydantic_ai.common_tools.web_fetch import web_fetch_tool
    from pydantic_ai.toolsets import RenamedToolset

    inner = FunctionToolset(
        [duckduckgo_search_tool(), web_fetch_tool(allow_local_urls=True)]
    )
    return RenamedToolset(inner, {'duckduckgo_search': 'web_search'})
