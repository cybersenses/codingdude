# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Project onboarding: first-run discovery of a project's conventions.

An agent taking over a project (from another agent or a fresh checkout) had
no enforced step to discover *where work is tracked* (GitHub Issues,
ROADMAP.md, docs) or the project's gates — so default behaviors won and work
went unlogged. The convention record is a durable workdir Memory entry whose
content starts with MARKER; its presence is the "onboarded" flag, so
detection, injection, and the UI memory panel all read the same source.

Best-effort by design: onboarding nudges, it never blocks a run.
"""

from __future__ import annotations

import json
import logging
import typing
from pathlib import Path

if typing.TYPE_CHECKING:
    from .memory import MemoryStore

MARKER = 'Project conventions:'

_ONBOARDING_BLOCK = """\
## Project onboarding (first session in this workdir)

No convention record exists for this project yet. Before doing the
requested work:
1. Discover the project's conventions: where work is tracked (GitHub
   Issues via `gh`, ROADMAP.md, docs/agents, other), the test/lint/
   type-check commands, and the key process docs (CLAUDE.md, AGENT.md,
   docs/adr). Run the `detect_conventions` seam for a marker-file
   first pass (runner, test command, line endings) and verify it.
2. Confirm your findings with the user via ask_user before relying on them.
3. Bank the record durably: call remember() with one entry starting
   exactly 'Project conventions: ' (scope 'workdir') covering tracker,
   commands, and docs.
Until the record exists, open a tracked item in the declared surface
before starting non-trivial work in this project.
"""


_SUFFIXES = {
    '.py': 'python', '.ts': 'typescript', '.tsx': 'typescript', '.js': 'javascript',
    '.jsx': 'javascript', '.mjs': 'javascript', '.go': 'go', '.rs': 'rust',
    '.java': 'java', '.cs': 'csharp', '.php': 'php', '.rb': 'ruby',
}
_SKIP_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.codegraph', 'dist'}


def detect_conventions(workdir: Path) -> dict:
    """Deterministic first-pass convention scan from marker files.

    Feeds step 1 of onboarding: the agent gets a head start (runner,
    test/lint commands, line endings, language mix) instead of guessing,
    then verifies with the user before banking the record. Never raises.
    """
    workdir = Path(workdir)
    out: dict = {'languages': {}, 'python': None, 'javascript': None, 'line_endings': None}

    def has(name: str) -> bool:
        return (workdir / name).exists()

    try:
        counts: dict[str, int] = {}
        for p in workdir.rglob('*'):
            if any(part in _SKIP_DIRS for part in p.relative_to(workdir).parts):
                continue
            if p.is_file():
                lang = _SUFFIXES.get(p.suffix.lower())
                if lang:
                    counts[lang] = counts.get(lang, 0) + 1
        out['languages'] = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    except OSError:
        pass

    if has('pyproject.toml'):
        try:
            pyproject = (workdir / 'pyproject.toml').read_text(encoding='utf-8', errors='replace')
        except OSError:
            pyproject = ''
        if '[tool.uv]' in pyproject or has('uv.lock'):
            runner = 'uv run'
        elif has('poetry.lock'):
            runner = 'poetry run'
        else:
            runner = 'python -m'
        out['python'] = {'runner': runner, 'tests': f'{runner} pytest'}

    if has('package.json'):
        try:
            import json

            scripts = json.loads(
                (workdir / 'package.json').read_text(encoding='utf-8')
            ).get('scripts', {})
        except (ValueError, OSError):
            scripts = {}
        out['javascript'] = {
            'pm': 'pnpm' if has('pnpm-lock.yaml') else 'yarn' if has('yarn.lock') else 'npm',
            'test': scripts.get('test'),
            'build': scripts.get('build'),
        }

    crlf = lf = 0
    try:
        sampled = 0
        for p in sorted(workdir.rglob('*')):
            if sampled >= 30:
                break
            if p.suffix.lower() not in _SUFFIXES or not p.is_file():
                continue
            if any(part in _SKIP_DIRS for part in p.relative_to(workdir).parts):
                continue
            data = p.read_bytes()[:20_000]
            if not data:
                continue
            sampled += 1
            if b'\r\n' in data:
                crlf += 1
            elif b'\n' in data:
                lf += 1
    except OSError as exc:
        logging.getLogger(__name__).warning('line-ending scan failed: %s', exc)
    out['line_endings'] = 'mixed' if crlf and lf else 'crlf' if crlf else 'lf' if lf else None
    return out


def onboarding_needed(store: MemoryStore, workdir: str | Path) -> bool:
    """True while the workdir has no 'Project conventions:' memory entry."""
    wd = str(workdir)
    return not any(
        r['scope'] == 'workdir' and r['workdir'] == wd and MARKER in r['content']
        for r in store.all_entries()
    )


def onboarding_block(workdir: str | Path | None = None) -> str:
    """The directive text injected into a not-yet-onboarded run's instructions.

    With a workdir, the deterministic first-pass scan (`detect_conventions`)
    is appended so the model starts from facts, not guesses.
    """
    block = _ONBOARDING_BLOCK
    if workdir is not None:
        try:
            block += (
                '\nFirst-pass convention scan (deterministic, verify before '
                'relying on it):\n```json\n'
                + json.dumps(detect_conventions(Path(workdir)), indent=2)
                + '\n```'
            )
        except OSError as exc:
            logging.getLogger(__name__).warning('convention scan failed: %s', exc)
    return block


def mark_onboarded(store: MemoryStore, workdir: str | Path, summary: str) -> int:
    """Bank the convention record; forces the MARKER prefix so detection holds."""
    content = summary.strip() or 'recorded'
    if MARKER not in content:
        content = f'{MARKER} {content}'
    return store.add(content, scope='workdir', workdir=str(workdir))
