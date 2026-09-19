"""Semantic "what changed" summary (#85, R38 phase 2).

For each file the working tree differs on vs HEAD, reports symbol-level
changes: Python via astdiff.describe_ast_change, JS/TS via tree-sitter
signatures (repo_map). Feeds the Diff tab's summary panel.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .astdiff import describe_ast_change
from .repo_map import js_signatures_source

_PY_EXTS = {'.py'}
_JS_EXTS = {'.js', '.jsx', '.mjs', '.ts', '.tsx'}


def changed_files(workdir: Path) -> list[str]:
    """Paths (posix, relative) differing from HEAD (staged + unstaged)."""
    result = subprocess.run(
        ['git', 'diff', 'HEAD', '--name-only'],
        cwd=workdir, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _before(workdir: Path, rel: str) -> str:
    result = subprocess.run(
        ['git', 'show', f'HEAD:{rel}'],
        cwd=workdir, capture_output=True, text=True, timeout=30,
    )
    return result.stdout if result.returncode == 0 else ''


def _after(workdir: Path, rel: str) -> str:
    path = workdir / rel
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def _sig_diff(before_sigs: list[str], after_sigs: list[str]) -> str:
    parts = [f'removed {s.strip()}' for s in sorted(set(before_sigs) - set(after_sigs))]
    parts += [f'added {s.strip()}' for s in sorted(set(after_sigs) - set(before_sigs))]
    return '; '.join(parts)


def summarize_file(workdir: Path, rel: str) -> dict:
    """One file's semantic change summary entry."""
    suffix = Path(rel).suffix
    before = _before(workdir, rel)
    after = _after(workdir, rel)
    if suffix in _PY_EXTS:
        summary = describe_ast_change(before, after)
    elif suffix in _JS_EXTS:
        summary = _sig_diff(
            js_signatures_source(before.encode(), suffix),
            js_signatures_source(after.encode(), suffix),
        )
    else:
        summary = ''
    return {'path': rel, 'summary': summary}


def summarize(workdir: Path) -> list[dict]:
    """Summary entries for every changed source file; [] on no diff."""
    workdir = Path(workdir)
    out = []
    for rel in changed_files(workdir):
        suffix = Path(rel).suffix
        if suffix in _PY_EXTS or suffix in _JS_EXTS:
            out.append(summarize_file(workdir, rel))
    return out
