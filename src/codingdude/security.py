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
"""Security gate (R47 #155): scan edited file content before it hits disk.

Two layers, one seam (`scan_source`):
- Python files: Bandit (in-process CLI module) flags dangerous constructs.
- All text files: curated regexes flag hardcoded secrets (AWS keys, tokens,
  private key blocks).
- Optional third layer (#157): bundled custom Semgrep rules when the
  semgrep binary is on PATH; skipped silently when absent (Bandit +
  secrets remain the fail-closed core).

Findings block the write via ModelRetry in tools.py — gate before disk,
not after. Bandit runs on a temp copy of the content so uncommitted drafts
are scannable without touching the workdir.
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404
import sys
from pathlib import Path

# Curated secret patterns (id -> regex). Deliberately narrow: high-signal
# only, to keep the gate from crying wolf.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        'AWS access key',
        re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    ),
    (
        'GitHub token',
        re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'),
    ),
    (
        'OpenAI-style API key',
        re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    ),
    (
        'private key block',
        re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    ),
)

_SECRET_LINE_CACHE_MAX = 1_000_000


def _secret_findings(source: str) -> list[dict]:
    findings: list[dict] = []
    for lineno, line in enumerate(source[:_SECRET_LINE_CACHE_MAX].splitlines(), 1):
        for label, rx in SECRET_PATTERNS:
            if rx.search(line):
                findings.append(
                    {
                        'id': 'SECRET',
                        'line': lineno,
                        'severity': 'HIGH',
                        'message': f'possible hardcoded secret: {label}',
                    }
                )
    return findings


def _bandit_findings(source: str, tmp_dir: Path, skip: str = '') -> list[dict]:
    scan_path = tmp_dir / '_security_gate_scan.py'
    scan_path.write_text(source, encoding='utf-8')
    argv = [sys.executable, '-m', 'bandit', '-q', '-f', 'json']
    if skip:
        argv += ['--skip', skip]
    argv.append(str(scan_path))
    # Sync on purpose: the edit tools that call this gate are synchronous.
    # Bounded timeout so a wedged scanner can never hang an edit.
    try:
        # Fixed argv, no shell: nothing user-controlled is executed.
        proc = subprocess.run(  # nosec B603
            argv,
            capture_output=True, text=True, timeout=60, check=False,
            cwd=tmp_dir,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('bandit timed out after 60s') from exc
    if not proc.stdout.strip():
        # Bandit prints nothing when clean (-q); no stdout with a failure
        # code means the scanner itself broke - fail closed.
        if proc.returncode != 0:
            raise RuntimeError(
                f'bandit failed (code {proc.returncode}): {proc.stderr[:400]}'
            )
        return []
    data = json.loads(proc.stdout)
    return [
        {
            'id': str(r.get('test_id', '?')),
            'line': int(r.get('line_number') or 0),
            'severity': str(
                (r.get('issue_severity') or '?').strip().title()
            ),
            'message': str(r.get('issue_text', '')),
        }
        for r in data.get('results', [])
    ]


def _semgrep_findings(source: str, tmp_dir: Path, suffix: str) -> list[dict]:
    """#157: run bundled custom rules over the content (optional layer).

    Skipped (returns []) when semgrep is not on PATH — Bandit + secret
    regexes remain the fail-closed core. Scanner failure raises (fail
    closed), matching the Bandit layer's policy.
    """
    import importlib.resources
    import shutil

    semgrep = shutil.which('semgrep')
    if semgrep is None:
        return []
    with importlib.resources.as_file(
        importlib.resources.files('codingdude') / 'semgrep_rules'
    ) as rules_dir:
        scan_path = tmp_dir / f'_security_gate_scan{suffix or ".txt"}'
        scan_path.write_text(source, encoding='utf-8')
        argv = [
            semgrep, 'scan', '--quiet', '--json',
            f'--config={rules_dir}', '--no-git-ignore',
            str(scan_path),
        ]
        try:
            # Fixed argv, no shell: nothing user-controlled is executed.
            proc = subprocess.run(  # nosec B603
                argv,
                capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=60, check=False,
                cwd=tmp_dir,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('semgrep timed out after 60s') from exc
    if proc.returncode not in (0, 1):
        # 0 = clean, 1 = findings; anything else is a scanner error.
        raise RuntimeError(
            f'semgrep failed (code {proc.returncode}): {proc.stderr[:400]}'
        )
    data = json.loads(proc.stdout) if proc.stdout.strip() else {'results': []}
    return [
        {
            'id': str(r.get('check_id', '?')),
            'line': int((r.get('start') or {}).get('line') or 0),
            'severity': str(
                ((r.get('extra') or {}).get('severity') or '?').title()
            ),
            'message': str((r.get('extra') or {}).get('message', '')),
        }
        for r in data.get('results', [])
    ]


def _is_test_file(rel: str) -> bool:
    """B101 (assert) is the point of pytest files - never gate on it there."""
    name = Path(rel).name
    return (
        'tests' in Path(rel).parts
        or name.startswith('test_')
        or name == 'conftest.py'
    )


def scan_source(
    rel: str, source: str, suffix: str, tmp_dir: Path
) -> list[dict]:
    """Scan file content; returns findings (empty = clean)."""
    findings = _secret_findings(source)
    if suffix == '.py':
        if _is_test_file(rel):
            findings.extend(_bandit_findings(source, tmp_dir, skip='B101'))
        else:
            findings.extend(_bandit_findings(source, tmp_dir))
    findings.extend(_semgrep_findings(source, tmp_dir, suffix))
    return findings


def format_findings(rel: str, findings: list[dict]) -> str:
    """Render security-gate findings as a readable multi-line report."""
    lines = [f'security gate: rejecting the write to {rel}:']
    lines.extend(
        f'  - :{f["line"]} [{f["severity"]}] {f["id"]}: {f["message"]}'
        for f in findings
    )
    lines.append('Fix the flagged issues and retry the edit with safe code.')
    return '\n'.join(lines)
