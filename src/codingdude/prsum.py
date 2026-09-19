"""PR summary generation (R33 #66): compose a pull-request body from git
log/diff plus AST semantic summaries for changed Python files.

Read-only: pure `git` queries against the workdir, no gates needed. The
agent passes the returned markdown to `gh_pr_create` (which stays
always-gated).
"""

import asyncio
from pathlib import Path

from .astdiff import describe_ast_change
from .tools import run_captured


async def _git(workdir: Path, *args: str) -> str:
    cap = await run_captured(['git', *args], cwd=workdir, timeout=30)
    if cap is None or cap.code != 0:
        return ''
    return cap.stdout


async def pr_summary_async(workdir: Path | str, base: str = 'origin/main') -> str:
    """Markdown PR body: commits, diff stat, and per-file AST summaries.

    Returns a readable error line when `base` is unknown or there are no
    commits between base and HEAD.
    """
    workdir = Path(workdir)
    log = await _git(workdir, 'log', '--oneline', f'{base}..HEAD')
    if not log:
        return f'no commits between {base} and HEAD'
    stat = await _git(workdir, 'diff', '--stat', f'{base}..HEAD')
    files = await _git(workdir, 'diff', '--name-only', f'{base}..HEAD')

    sections = [f'## Commits\n{log.strip()}']
    if stat:
        sections.append(f'## Changes\n```\n{stat.strip()}\n```')

    ast_lines: list[str] = []
    for path in files.splitlines():
        path = path.strip()
        if not path.endswith('.py'):
            continue
        before_cap = await run_captured(
            ['git', 'show', f'{base}:{path}'], cwd=workdir, timeout=30)
        after_cap = await run_captured(
            ['git', 'show', f'HEAD:{path}'], cwd=workdir, timeout=30)
        before = before_cap.stdout if before_cap and before_cap.code == 0 else ''
        after = after_cap.stdout if after_cap and after_cap.code == 0 else ''
        if not after:
            continue
        summary = describe_ast_change(before, after)
        if summary:
            ast_lines.append(f'- `{path}`: {summary.replace(chr(10), "; ")}')
    if ast_lines:
        sections.append('## Semantic summary\n' + '\n'.join(ast_lines))

    return '\n\n'.join(sections)


def pr_summary(workdir: Path | str, base: str = 'origin/main') -> str:
    """Sync wrapper so tools and tests can call this directly."""
    return asyncio.run(pr_summary_async(workdir, base))
