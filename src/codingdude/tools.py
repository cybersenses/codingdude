"""Read-only coding tools: list, read, grep, glob — all confined to the Workdir."""

import re
from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

MAX_READ_BYTES = 256 * 1024
MAX_GREP_RESULTS = 50
SKIP_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.mypy_cache', '.pytest_cache'}


def build_toolset(workdir: Path) -> FunctionToolset:
    """Build the read-only toolset bound to a Workdir (via closure)."""

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

    return FunctionToolset([list_dir, read_file, grep, glob])
