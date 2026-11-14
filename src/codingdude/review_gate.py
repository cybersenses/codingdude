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
"""Pre-push review gate: a push carries a review of the exact diff it publishes.

Why this exists: pre-push two-axis review was mandated as prose (project notes
#22/#25) with no enforcement point anywhere. `.git/hooks` is empty,
`core.hooksPath` is unset, `gates.bat` runs ruff/mypy/pytest only, and the sole
automated nudge was a string appended to the `git push` *output* — it fired
after the irreversible act it was supposed to prevent. So review stayed a
multi-step ritual that a turn could simply not perform.

This turns it into state: `git push` refuses unless a record exists whose
`diff_key` equals the sha256 of the content about to be published — the
committed range (`git diff BASE...HEAD`) plus the working tree. The record is
written only by `record_review`, which demands evidence per review axis.
Content-addressed, so amending or rebasing without changing the diff keeps a
review valid; changing one byte of it voids the record.

Stated plainly, so nobody over-claims it: the gate does not verify the evidence.
An agent can record a review it did not perform — the same accepted boundary as
`update_execution_step` (#293). It guarantees publishing requires a deliberate,
recorded, axis-labelled act; it cannot guarantee the review was competent.

Ceiling: `<git-dir>/codingdude/review.json` is per-clone and last-write-wins.
"""

import hashlib
import json
import subprocess  # nosec B404 - fixed-argv git only, no shell
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_BASE = 'origin/main'
RECORD_NAME = 'review.json'
#: git's empty tree — the base for a branch with no remote ref yet, so a first
#: push reviews its whole content instead of an empty range.
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'


class ReviewGateError(RuntimeError):
    """A push was attempted without a review of the content being pushed."""


def _git(workdir: Path, *args: str) -> str:
    """Run git and return stdout, or '' when git cannot answer.

    '' is never load-bearing for a *decision* here: `resolve_base` fails closed
    on an unanswerable repo (see `require_review`) rather than letting an empty
    range produce an empty key that would match an empty record.
    """
    try:
        proc = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ['git', *args], cwd=workdir, capture_output=True,
            encoding='utf-8', errors='replace', timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    return (proc.stdout or '') if proc.returncode == 0 else ''


def resolve_base(workdir: Path, base: str = '') -> str:
    """The concrete commit a review range starts from — never an empty range.

    Caller-supplied bases are the bypass this closes: `base='HEAD'` used to make
    the committed range empty, so a record over `sha256('')` matched any commit.
    Auto-resolution is therefore the default, and a branch with no remote ref
    yet (first push, fork, non-`main` default) is reviewed against the empty
    tree — its whole content, not nothing.
    """
    if base:
        return base
    if not _git(workdir, 'rev-parse', '--verify', 'HEAD').strip():
        return EMPTY_TREE
    return _git(workdir, 'merge-base', DEFAULT_BASE, 'HEAD').strip() or EMPTY_TREE


def collect_review_diff(workdir: Path, base: str = '') -> str:
    """The content a review must cover: committed range + working tree.

    One definition, two callers (the reviewer and the gate). `git diff HEAD`
    alone was the old behaviour and reviews *nothing* after a commit — which is
    exactly when a pre-push review runs.
    """
    start = resolve_base(workdir, base)
    committed = _git(workdir, 'diff', start, 'HEAD')
    working = _git(workdir, 'diff', 'HEAD')
    return committed + working


def review_diff_key(workdir: Path, base: str = '') -> str:
    """Content hash of the diff a review would cover."""
    return hashlib.sha256(
        collect_review_diff(workdir, base).encode('utf-8', 'replace')
    ).hexdigest()


def record_path(workdir: Path) -> Path:
    """`<git-dir>/codingdude/review.json` — per clone, outside the work tree.

    The workdir fallback covers a directory git does not know about; nothing can
    be pushed from there, so the degraded key is harmless rather than a bypass.
    """
    git_dir = _git(workdir, 'rev-parse', '--absolute-git-dir').strip()
    root = Path(git_dir) if git_dir else Path(workdir) / '.git'
    return root / 'codingdude' / RECORD_NAME


def record_review(
    workdir: Path,
    *,
    standards_evidence: str,
    spec_evidence: str,
    base: str = '',
    findings: int = 0,
    branch: str = '',
    verdict: str = '',
) -> dict:
    """Record a two-axis review of the current diff. Raises when an axis is blank.

    Evidence is what the reviewer reported per axis — a finding that was fixed,
    or an explicit 'no findings'. Blank means the axis was never run.
    """
    missing = [
        name for name, value in (
            ('standards_evidence', standards_evidence),
            ('spec_evidence', spec_evidence),
        )
        if not (value or '').strip()
    ]
    if missing:
        raise ReviewGateError(
            f'record_review: {" and ".join(missing)} is empty. A pre-push review '
            'covers BOTH axes (Standards: does it follow the repo standards; '
            'Spec: does it do what the ticket asked). Report what each axis '
            'found — a fixed finding, or an explicit "no findings".'
        )
    if findings < 0:
        raise ReviewGateError(f'record_review: findings must be ≥ 0, got {findings}')
    head = _git(workdir, 'rev-parse', 'HEAD').strip()
    payload = {
        'diff_key': review_diff_key(workdir, base),
        'base': resolve_base(workdir, base),
        'head': head,
        'branch': branch or _git(workdir, 'rev-parse', '--abbrev-ref', 'HEAD').strip(),
        'verdict': verdict or ('clean' if findings == 0 else 'findings_fixed'),
        'findings': int(findings),
        'standards_evidence': standards_evidence.strip(),
        'spec_evidence': spec_evidence.strip(),
        'recorded_at': datetime.now(UTC).isoformat(timespec='seconds'),
    }
    path = record_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return payload


def require_review(workdir: Path, branch: str = '') -> dict:
    """Return the review record covering what a push would publish, or raise.

    Callers turn the error into a ModelRetry so the model gets a readable,
    actionable refusal instead of a stack trace.
    """
    path = record_path(workdir)
    if not path.exists():
        raise ReviewGateError(
            'push refused: no pre-push review is on record. Run the code-review '
            'flow over this branch (Standards + Spec axes — delegate both, verify '
            'every finding against the code, fix what is real), then call '
            'record_review(standards=..., spec=...) and push again. Post-push '
            'review is a failsafe, not the review.'
        )
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewGateError(
            f'push refused: the review record at {path} is unreadable ({exc}). '
            'Re-run the review and record it again.'
        ) from None
    # The record must describe the ref actually being pushed: a review of this
    # branch does not authorize pushing a different one. Compared by name, not
    # tip — an amend legitimately moves the tip without changing the diff, and
    # the content key below is what decides whether the diff still matches.
    recorded_branch = record.get('branch') or ''
    if branch and recorded_branch and branch != recorded_branch:
        raise ReviewGateError(
            f'push refused: the recorded review covers branch '
            f'{recorded_branch!r}, you are pushing {branch!r}. Review and record '
            'the branch you are pushing.'
        )
    current = review_diff_key(workdir, record.get('base') or '')
    if current != record.get('diff_key'):
        raise ReviewGateError(
            f'push refused: the diff changed since the review recorded at '
            f'{record.get("recorded_at", "?")} (reviewed '
            f'{str(record.get("diff_key"))[:12]}, now {current[:12]}) — findings '
            'were fixed or edits landed after the review. Review the current '
            'diff and call record_review again.'
        )
    return record
