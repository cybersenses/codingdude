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
"""DE-6 (#300): the long-run work mode — levels, risk digest, publish cycle.

Pure seam module: level validation, the operator-facing risk digest (the
PRD §"Risks of long-running autonomy" line set), the publish-cycle branch
naming and preauthorization rules, and the findings parser that turns
CI/reviewer feedback into structured DATA. Enforcement lives at the
boundaries that consume it (approvals.decide, the git toolset's scope
pins, the execution toolset's convergence gate).
"""

from __future__ import annotations

import re

LEVELS = ('assisted', 'unattended')

#: The publish cycle pushes work branches matching this prefix — never main,
#: never any other naming. The prefix is the enforcement, not a convention.
PUBLISH_BRANCH_PREFIX = 'codingdude/longrun-'

#: The convergence gate card's scope (assisted): push the work branch +
#: open a draft PR + fix CI/reviewer findings on that branch. Merge is
#: explicitly OUTSIDE the scope — push consent is not merge consent.
PUBLISH_SCOPE = (
    'push this run\'s work branch (codingdude/longrun-*) and open a DRAFT '
    'PR, then fix CI/reviewer findings on that branch'
)


def validate_level(level: str | None) -> str | None:
    """Fail-fast level check (unknown = caller error, never a silent default)."""
    if level is None:
        return None
    if level not in LEVELS:
        raise ValueError(
            f"unknown long_run level {level!r} — use 'assisted' or "
            "'unattended'"
        )
    return level


def risk_digest(level: str, tier: str, publish_authorized: bool) -> list[str]:
    """The risks-of-long-running-autonomy digest printed at run start.

    The remote-publication line appears only when the publish cycle is
    authorized — informed consent names exactly what was authorized.
    """
    lines = [
        f'long-run level: {level} (sandbox tier: {tier})',
        'Risks of long-running autonomy:',
        '- hours of runway amplify a wrong early turn; the evidence gate '
        'and evaluator cap exist to catch drift, not to prevent it',
        '- unattended runs auto-approve ordinary shell work; the '
        'always-gated tier (remote mutations, destructive ops) still stops '
        'the run unless this level is unattended',
        '- the sandbox container has no egress isolation beyond the '
        'container boundary (decision #98); it holds no credentials',
    ]
    if publish_authorized:
        lines.append(
            '- PUBLISH CYCLE AUTHORIZED: this run may push its '
            'codingdude/longrun-* work branch and open a DRAFT PR on the '
            'remote (CI minutes consumed, branch visible to collaborators); '
            'merge and draft->ready stay human-only'
        )
    return lines


def publish_branch(run_id: str | None) -> str:
    """The work branch for a long run's publish cycle."""
    short = (run_id or 'run').replace('-', '')[:12]
    return f'{PUBLISH_BRANCH_PREFIX}{short}'


def push_preauthorized(policy, branch: str) -> bool:
    """True when this push may flow without its always-gated card.

    The scope pins are enforced HERE, not in docs: authorization applies
    only to codingdude/longrun-* branches (main is unreachable by
    construction), only while the authorization is set, and only in a
    long-run mode. Force-push has no parameter anywhere in the toolchain;
    draft->ready and merge have no agent tools at all.
    """
    mode = getattr(policy, 'mode', None)
    return bool(
        mode in LEVELS
        and getattr(policy, 'publish_authorized', False)
        and branch.startswith(PUBLISH_BRANCH_PREFIX)
    )


_FILE_REF = re.compile(
    r'[\w./\\+-]+\.[A-Za-z]{1,8}(?::\d+)?'
)


def findings_from_gh(payload: dict) -> list[dict]:
    """Parse `gh pr view --json reviews,comments` output into structured
    findings — DATA the fix loop reads, never instructions it executes.

    Each finding: {source, author, file?, note}. `file` is the first
    repo-path-looking token in the body; `note` is the body, capped — the
    fix loop reads it as a report about the code, and the evaluator
    re-grades whatever the loop does against the ticket contract.
    """
    out: list[dict] = []
    for source, key in (('review', 'reviews'), ('comment', 'comments')):
        for item in payload.get(key) or []:
            body = str(item.get('body') or '').strip()
            if not body:
                continue
            file = next(
                (m.group(0).replace('\\', '/').rstrip('.,;:)')
                 for m in _FILE_REF.finditer(body)
                 if '/' in m.group(0) or m.group(0).count('.') >= 1),
                None,
            )
            out.append({
                'source': source,
                'author': item.get('author', {}).get('login')
                if isinstance(item.get('author'), dict)
                else item.get('author'),
                'file': file,
                'note': body[:500],
            })
    return out
