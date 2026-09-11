"""Coding tools: list, read, grep, glob, plus surgical edits — all confined to the Workdir."""

import re
from collections.abc import Callable
from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from .approvals import DENIED, NEEDS_GATE
from .config import ThinkingSetting
from .directives import project_directives_guard
from .errors import GateRequired

MAX_READ_BYTES = 256 * 1024
MAX_GREP_RESULTS = 50
MAX_FILE_BYTES = 2 * 1024 * 1024  # grep: skip files larger than this
SKIP_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache'}
SECRET_MARKERS = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')


def shell_argv(command: str, shell_bin: str = 'bash') -> list[str]:
    """Argv to run `command` under the configured shell (bash or powershell).

    One place, so the shell tool / coverage / fix-loop can't drift onto a
    hardcoded `bash` on Windows (self-review M10).
    """
    if shell_bin == 'powershell':
        return ['powershell', '-NoProfile', '-Command', command]
    return ['bash', '-c', command]


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

EditEmitter = Callable[[dict], None]


def build_toolset(
    workdir: Path,
    on_edit: EditEmitter | None = None,
    read_only: bool = False,
    approvals=None,
    capture: Callable[[Path], None] | None = None,
) -> FunctionToolset:  # noqa: C901
    """Build the toolset bound to a Workdir (via closure). read_only strips edits.
    `capture(abs_path)` snapshots a file before the agent modifies it (checkpoints).

    `approvals` (an ApprovalPolicy) gates AGENT.md edits — the Project Context
    changes only with explicit consent (spec story 26).
    """

    def resolve(path: str) -> Path:
        target = (workdir / path).resolve()
        try:
            target.relative_to(workdir.resolve())
        except ValueError:
            raise ModelRetry(
                f'Path {path!r} is outside the Workdir. '
                'Only paths inside the Workdir are accessible.'
            ) from None
        return target

    def list_dir(path: str = '.') -> str:
        target = resolve(path)
        if not target.exists():
            return f'(directory not found: {path} — list_dir "." to see what exists)'
        entries = sorted(
            target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
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
        if not target.exists():
            return f'(path not found: {path} — list_dir "." to see what exists)'
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
        root = workdir.resolve()
        # Refuse patterns that climb out of the Workdir (mirrors resolve()).
        if Path(pattern).is_absolute() or '..' in Path(pattern).parts:
            raise ModelRetry(
                f'Glob pattern {pattern!r} escapes the Workdir. '
                'Use a relative pattern inside the project.'
            )
        matches = sorted(
            str(m.relative_to(root)) for m in root.glob(pattern) if m.is_file()
        )
        return '\n'.join(matches) or '(no matches)'

    def emit_edit(path: str, before: str, after: str) -> None:
        if on_edit:
            on_edit({'type': 'EDIT_APPLIED', 'kind': 'edit', 'path': path, 'before': before, 'after': after})

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
        if capture:
            capture(resolve(path))
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
        if capture:
            capture(resolve(path))
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
        # One source of truth for what a pattern covers — never the bare
        # leading token, or an interpreter approval unlocks the interpreter
        # (self-review C1).
        pattern = policy.pattern_for(command)
        policy.approve_pattern(pattern)
        if policy.on_pattern:
            policy.on_pattern(pattern)


def build_shell_toolset(workdir: Path, policy, shell_bin: str = 'bash') -> FunctionToolset:
    """The shell tool, gated by the ApprovalPolicy."""

    def _mask_workdir(command: str) -> str:
        """Blank out references to the Workdir itself before the approval
        decision: `cd G:/proj && ...` targets the project the agent is
        already confined to and must not read as an outside path."""
        resolved = workdir.resolve()
        backslash = chr(92)
        variants = {
            str(workdir),
            str(resolved),
            str(resolved).replace(backslash, '/'),
            str(resolved).lower().replace(backslash, '/'),
            '/' + workdir.drive.lower() + str(resolved)[2:].replace(backslash, '/'),
        }
        masked = command
        for variant in variants:
            if variant:
                masked = masked.replace(variant, '.')
        return masked

    async def shell(command: str, timeout: int = 120) -> str:
        decision = policy.decide(_mask_workdir(command))
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=decision == DENIED)
        import asyncio

        argv = shell_argv(command, shell_bin)
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


def build_delegation_toolset(
    workdir: Path, subagent_model, thinking: ThinkingSetting | None = None
) -> FunctionToolset:
    """The `delegate` tool: spawn a read-only Subagent on the cheap model.

    Subagents never see edit/write/shell/delegation tools, so Delegation
    can't route around Approval tiers.
    """

    async def delegate(task: str) -> str:
        from pydantic_ai import Agent
        from pydantic_ai.settings import ModelSettings

        from .prompts import load_prompt

        settings: ModelSettings = ModelSettings(timeout=300)
        if thinking is not None:
            settings['thinking'] = thinking
        sub_agent: Agent = Agent(
            model=subagent_model,
            instructions=load_prompt('delegation'),
            toolsets=[build_toolset(workdir, read_only=True)],
            model_settings=settings,
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
        summary = f'exit {code}\n{out}' if out else f'exit {code}'
        return summary

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

        # `source` is model-supplied: keep it a relative in-Workdir path and
        # pass argv (never a shell), so `.; rm -rf /` cannot execute (H3).
        if not source or Path(source).is_absolute() or '..' in Path(source).parts:
            raise ModelRetry(f'{source!r} is not a relative in-Workdir coverage source.')
        argv = ['python', '-m', 'pytest', f'--cov={source}',
                '--cov-report=term-missing', '-q']
        command = ' '.join(argv)
        decision = policy.decide(command)
        if decision in (NEEDS_GATE, DENIED):
            await _resolve_gate(policy, command, always=decision == DENIED)
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            *argv,
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


def build_knip_toolset(workdir: Path) -> FunctionToolset:
    """The `find_unused_exports` tool for JS/TS projects: runs knip from the
    project's own devDependencies (never auto-installing). Graceful when
    knip isn't set up."""

    async def find_unused_exports() -> str:
        if not (workdir / 'package.json').exists():
            return 'no package.json — knip only applies to JS/TS projects'
        import asyncio

        proc = await asyncio.create_subprocess_shell(
            'npx --no-install knip --reporter compact',
            cwd=workdir, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=scrubbed_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except TimeoutError:
            proc.kill()
            return 'knip timed out after 300s'
        out = (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()
        code = proc.returncode if proc.returncode is not None else -1
        if code != 0 and 'knip' not in out and len(out) < 200:
            return (
                'knip is not installed in this project. Add it as a devDependency '
                '(npm i -D knip) to enable unused-export and unused-dependency detection.'
            )
        return f'exit {code}\n{out[:6000]}'

    return FunctionToolset([find_unused_exports])


def build_ci_toolset(workdir: Path) -> FunctionToolset:
    """CI tools via the gh CLI. Read-only (run list, failed logs) — auto tier.

    `gh run rerun`/watch and anything mutating stay in the shell's
    always-gated tier; never auto-approved here."""

    async def _gh(argv: list[str], timeout: int = 120) -> str:
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            'gh', *argv, cwd=workdir, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=scrubbed_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return 'gh timed out'
        out = (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()
        code = proc.returncode if proc.returncode is not None else -1
        summary = f'exit {code}\n{out}' if out else f'exit {code}'
        return summary

    async def ci_status(branch: str = '') -> str:
        """Latest CI run statuses for the current repo (via gh)."""
        argv = ['run', 'list', '--limit', '5']
        if branch:
            argv += ['--branch', branch]
        return await _gh(argv)

    async def ci_failures(run_id: str = '') -> str:
        """Failed step names and log excerpts for a CI run (via gh)."""
        argv = ['run', 'view']
        if run_id:
            argv.append(run_id)
        argv += ['--log-failed']
        return await _gh(argv)

    return FunctionToolset([ci_status, ci_failures])


def build_audit_toolset(workdir: Path) -> FunctionToolset:
    """`dependency_audit`: vulnerability scan via pip-audit (Python) and
    npm audit (JS/TS). Read-only; auto tier. Reports what it finds; missing
    tools are surfaced so the agent can suggest installation."""

    async def _run(cmd: list[str], timeout: int = 300) -> str:
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=workdir, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=scrubbed_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return 'audit timed out'
        return (stdout.decode(errors='replace') + stderr.decode(errors='replace')).strip()

    async def dependency_audit() -> str:
        sections = []

        if (workdir / 'requirements.txt').exists() or (workdir / 'pyproject.toml').exists():
            pip_result = await _run(['pip-audit', '--progress-spinner', 'off'])
            if 'No known vulnerabilities found' in pip_result or 'no known vulnerabilities' in pip_result.lower():
                sections.append('pip-audit: no known vulnerabilities')
            elif 'is not recognized' in pip_result or 'No module named pip_audit' in pip_result:
                sections.append('pip-audit: not installed (pip install pip-audit)')
            else:
                sections.append(f'pip-audit:\n{pip_result[:3000]}')

        if (workdir / 'package.json').exists():
            npm_result = await _run(['npm', 'audit', '--json'])
            import json as _json

            try:
                report = _json.loads(npm_result)
                vulns = report.get('metadata', {}).get('vulnerabilities', {})
                total = vulns.get('total', 0)
                sections.append(
                    f'npm audit: {total} vulnerabilit{"y" if total == 1 else "ies"} '
                    f'(critical: {vulns.get("critical", 0)}, high: {vulns.get("high", 0)}, '
                    f'moderate: {vulns.get("moderate", 0)}, low: {vulns.get("low", 0)})'
                )
            except _json.JSONDecodeError:
                sections.append(f'npm audit: {npm_result[:500]}')

        return '\n\n'.join(sections) or '(no supported project manifests found)'

    return FunctionToolset([dependency_audit])
