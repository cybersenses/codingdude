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
"""R80-5 #297 (DE-3 remainder): the long-run sandbox lane.

A long run (``long_run`` request field set) prefers the container tier: one
sandbox is auto-created at run start and shell work routes through
``exec_in_sandbox_dir`` — the shared R17 core — so approval gating, tier
labeling, and container exec cannot drift per-caller. When Docker is absent
or the sandbox cannot be created (no git history, container start failure),
the run proceeds on the HOST tier and says so — in the LANE trace event (the
start banner), in the agent's instructions, and in the run's summary note —
never silently (REQ-3 honesty; M5 measures shell work via the tier lines in
the trace).

The worktree/branch is the run's work product and survives the run; only the
idle container is removed at run end (best-effort). ``sandbox_promote`` is
untouched and stays always-gated.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .sandbox import (
    CONTAINER_IMAGE,
    create_sandbox,
    exec_in_sandbox_dir,
    remove_container,
)

logger = logging.getLogger(__name__)

LANE_PREFIX = 'longrun-'

#: exec_in_sandbox_dir summaries start with 'exit <code>' — the one parse
#: the fix loop needs to turn a lane result into pass/fail.
_EXIT_RE = re.compile(r'^exit (-?\d+)')


def exit_code_of(text: str) -> int | None:
    """The exit code of an exec_in_sandbox_dir summary, None when unparsable."""
    m = _EXIT_RE.match(text.strip())
    return int(m.group(1)) if m else None


#: git identity for the bootstrap seed commit — deterministic, never relies
#: on ambient global config (a fresh scratch project may have none).
_BOOTSTRAP_IDENTITY = (
    '-c', 'user.name=codingdude', '-c', 'user.email=codingdude@local',
)
_BOOTSTRAP_COMMIT_MSG = 'initial commit (long-run lane bootstrap)'


def ensure_commit_ready(workdir: Path) -> str | None:
    """#306: make a commitless workdir branchable so the container tier can
    engage.

    `git worktree add` needs at least one commit; scratch-project bootstrap
    tasks start with no repo at all. This seeds the missing baseline: git
    init when needed, then one seed commit of the current state (an empty
    workdir gets an empty root commit). The commit lands on the default
    branch of the long-run workdir — deliberate: the run's own changes stay
    isolated on branch codingdude/<lane> while the seed state is the base
    every future run starts from. Returns None when the workdir is
    branchable, else a readable reason (the lane degrades honestly; this
    never raises).
    """
    import shutil
    import subprocess  # nosec B404 - fixed-argv git only, no shell

    git = shutil.which('git') or 'git'

    def _git(*args: str) -> tuple[int, str]:
        proc = subprocess.run(
            [git, *args], cwd=workdir, capture_output=True, text=True,
        )  # nosec B603 - fixed argv, no shell
        return proc.returncode, (proc.stdout + proc.stderr).strip()

    code, out = _git('rev-parse', '--git-dir')
    if code != 0:
        code, out = _git('init')
        if code != 0:
            return f'git init failed: {out}'
    code, _ = _git('rev-parse', 'HEAD')
    if code == 0:
        return None  # already branchable — touch nothing
    code, out = _git(*_BOOTSTRAP_IDENTITY, 'add', '-A')
    if code != 0:
        return f'git add failed: {out}'
    code, out = _git(*_BOOTSTRAP_IDENTITY, 'commit', '-m', _BOOTSTRAP_COMMIT_MSG)
    if code == 0:
        return None
    # Nothing staged (empty workdir): an empty root commit still gives the
    # worktree a HEAD to branch from.
    code, out = _git(
        *_BOOTSTRAP_IDENTITY, 'commit', '--allow-empty', '-m',
        _BOOTSTRAP_COMMIT_MSG)
    if code != 0:
        return f'git commit failed: {out}'
    return None


@dataclass
class LongRunLane:
    """One sandbox lane for one long run (DE-3)."""

    workdir: Path
    name: str
    tier: str  # 'container' | 'host'
    sandbox_ready: bool
    reason: str | None  # set when degraded: why the container tier is off
    policy: object | None = None

    @classmethod
    async def create(
        cls, workdir: Path, run_id: str | None, policy=None,
    ) -> LongRunLane:
        """Probe Docker and create the lane's sandbox; degrade honestly when
        anything blocks the container tier (never raise)."""
        name = LANE_PREFIX + (run_id or 'run')
        from .sandbox import docker_usable

        if not docker_usable():
            return cls(
                workdir=workdir, name=name, tier='host', sandbox_ready=False,
                reason='Docker unavailable — shell commands run on the host '
                       'tier (no container isolation)',
                policy=policy,
            )
        # #306: bootstrap a commitless workdir. Scratch-project tasks START
        # with no repo — without this, `git worktree add` failed and every
        # bootstrap run degraded to the host tier: the one mode that exists
        # to make the first commit could never reach the container. The seed
        # commit lands on the default branch of the long-run workdir (gates
        # are auto-approved on this path by construction); the run's own
        # work stays isolated on branch codingdude/<name>.
        bootstrap = ensure_commit_ready(workdir)
        if bootstrap is not None:
            logger.warning('lane bootstrap failed: %s', bootstrap)
            return cls(
                workdir=workdir, name=name, tier='host', sandbox_ready=False,
                reason=f'lane bootstrap failed ({bootstrap}) — shell '
                       'commands run on the host tier',
                policy=policy,
            )
        result = await create_sandbox(
            workdir, name, 'container', reuse_worktree=True)
        if result.startswith('sandbox ready'):
            return cls(
                workdir=workdir, name=name, tier='container',
                sandbox_ready=True, reason=None, policy=policy,
            )
        logger.warning('lane sandbox creation failed: %s', result)
        return cls(
            workdir=workdir, name=name, tier='host', sandbox_ready=False,
            reason=f'container tier unavailable ({result}) — shell commands '
                   'run on the host tier',
            policy=policy,
        )

    @property
    def event(self) -> dict:
        """The LANE trace event: the run's start banner + tier line."""
        event: dict = {
            'type': 'LANE',
            'tier': self.tier,
            'sandbox': self.name,
            'degraded': not self.sandbox_ready,
        }
        if self.reason:
            event['reason'] = self.reason
        return event

    def instructions_block(self) -> str:
        """What the agent must know about where its shell commands run."""
        if self.sandbox_ready:
            return (
                '## Execution tier\n'
                f'Long-run lane: shell commands execute inside container '
                f'"{self.name}" ({CONTAINER_IMAGE}); the repo worktree is '
                f'mounted at /workspace on branch codingdude/{self.name}. '
                'File edits still happen in the agent\'s workdir view; use '
                'the shell for builds/tests inside the container.'
            )
        return (
            '## Execution tier\n'
            f'Long-run lane DEGRADED: {self.reason}. Shell commands run on '
            'the HOST with no container isolation — keep commands '
            'workdir-scoped and avoid anything destructive beyond the task.'
        )

    def summary_note(self) -> str | None:
        """The run-summary line for a degraded tier (None on container tier —
        every exec result already carries the container tier line)."""
        if self.sandbox_ready:
            return None
        return f'lane: {self.reason}'

    async def run(self, command: str) -> str:
        """Execute one shell command through the shared R17 core (gating,
        container exec, tier line — one implementation)."""
        return await exec_in_sandbox_dir(
            self.workdir, self.name, command, policy=self.policy,
        )

    async def cleanup(self) -> None:
        """Remove the idle container at run end (worktree/branch kept — that
        is the run's work product). Best-effort, never raises."""
        if not self.sandbox_ready:
            return
        try:
            remove_container(self.name)
        except Exception as exc:  # noqa: BLE001 — hygiene must never fail the run
            logger.warning('lane container cleanup failed: %s', exc)
