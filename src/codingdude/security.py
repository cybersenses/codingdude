"""Security gate (R47 #155): scan edited file content before it hits disk.

Two layers, one seam (`scan_source`):
- Python files: Bandit (in-process CLI module) flags dangerous constructs.
- All text files: curated regexes flag hardcoded secrets (AWS keys, tokens,
  private key blocks).

Findings block the write via ModelRetry in tools.py — gate before disk,
not after. Bandit runs on a temp copy of the content so uncommitted drafts
are scannable without touching the workdir.
"""

from __future__ import annotations

import json
import re
import subprocess
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


def _bandit_findings(source: str, tmp_dir: Path) -> list[dict]:
    scan_path = tmp_dir / '_security_gate_scan.py'
    scan_path.write_text(source, encoding='utf-8')
    # Sync on purpose: the edit tools that call this gate are synchronous.
    # Bounded timeout so a wedged scanner can never hang an edit.
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, '-m', 'bandit', '-q', '-f', 'json',
             str(scan_path)],
            capture_output=True, text=True, timeout=60, check=False,
            cwd=tmp_dir,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('bandit timed out after 60s') from exc
    if not proc.stdout.strip():
        # Bandit prints nothing when clean (-q); no stdout with a failure
        # code means the scanner itself broke — fail closed.
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


def scan_source(
    rel: str, source: str, suffix: str, tmp_dir: Path
) -> list[dict]:
    """Scan file content; returns findings (empty = clean)."""
    findings = _secret_findings(source)
    if suffix == '.py':
        findings.extend(_bandit_findings(source, tmp_dir))
    return findings


def format_findings(rel: str, findings: list[dict]) -> str:
    lines = [f'security gate: rejecting the write to {rel}:']
    lines.extend(
        f'  - :{f["line"]} [{f["severity"]}] {f["id"]}: {f["message"]}'
        for f in findings
    )
    lines.append('Fix the flagged issues and retry the edit with safe code.')
    return '\n'.join(lines)
