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
"""GitHub issue mirroring for planning items (R53).

The user's standing convention — every ticket/roadmap item is logged locally
first, then mirrored to a GitHub issue — is enforced here, in code, because
agent discipline proved unreliable. The mirror is strictly best-effort:
when `gh` is missing, the repo has no GitHub remote, or auth fails, every
call logs one line and returns None. Local planning state is the source of
truth; GitHub never blocks a local write.
"""

import logging
import re
import shutil
import subprocess  # nosec B404 - gh CLI boundary; args are internal, not user input
import tempfile
from pathlib import Path

from .config import load_config

logger = logging.getLogger(__name__)

_GH_TIMEOUT = 20
_ISSUE_URL_RE = re.compile(r'/issues/(\d+)\s*$')


class GitHubMirror:
    """Best-effort GitHub issue mirror via the `gh` CLI.

    Availability is probed once per workdir (gh on PATH + a github.com
    `origin` remote + `gh auth status`) and cached. Disable entirely with
    `[planning] github_mirror = false` in config.toml.
    """

    _available: dict[str, bool] = {}  # class-level: probed once per process

    def __init__(self) -> None:
        self._label_ensured = False
        self._enabled = True
        try:
            self._enabled = load_config().planning.github_mirror
        except Exception:  # noqa: BLE001 -- mirror must never break planning
            logger.info('GitHub mirror: config unreadable, defaulting to on')

    # ---- availability ----

    def available(self, workdir: str) -> bool:
        if not self._enabled:
            return False
        if workdir in self._available:
            return self._available[workdir]
        ok = self._probe(workdir)
        self._available[workdir] = ok
        if not ok:
            logger.info('GitHub mirror skipped: gh/GitHub remote unavailable for %s',
                        workdir)
        return ok

    def _probe(self, workdir: str) -> bool:
        if self._gh_path() is None:
            return False
        remote = self._gh(workdir, ['remote', 'get-url', 'origin'])
        if remote is None or 'github.com' not in remote.stdout:
            return False
        return self._gh(workdir, ['auth', 'status']) is not None

    @staticmethod
    def _gh_path() -> str | None:
        """Full path to the gh executable (None when not installed)."""
        return shutil.which('gh')

    # ---- public mirror operations (never raise) ----

    def create_issue(self, workdir: str, title: str, body: str) -> int | None:
        """Create an issue, return its number, or None when unavailable/failed."""
        if not self.available(workdir):
            return None
        self._ensure_done_label(workdir)
        with tempfile.NamedTemporaryFile(
            'w', suffix='.md', delete=False, encoding='utf-8'
        ) as f:
            f.write(body or '(no body)')
            body_path = f.name
        try:
            out = self._gh(workdir, ['issue', 'create',
                                     '--title', title,
                                     '--body-file', body_path])
        finally:
            try:
                Path(body_path).unlink()
            except OSError:
                pass
        if out is None:
            logger.warning('GitHub mirror: issue create failed for %r', title)
            return None
        m = _ISSUE_URL_RE.search(out.stdout.strip())
        if not m:
            logger.warning('GitHub mirror: could not parse issue number from %r',
                           out.stdout.strip())
            return None
        return int(m.group(1))

    def close_done(self, workdir: str, issue_number: int) -> bool:
        """Close an issue as completed and label it `done`. Best-effort."""
        if not self.available(workdir):
            return False
        self._ensure_done_label(workdir)
        ok = self._gh(workdir, ['issue', 'close', str(issue_number),
                                '--reason', 'completed']) is not None
        labeled = self._gh(workdir, ['issue', 'edit', str(issue_number),
                                     '--add-label', 'done']) is not None
        if not ok or not labeled:
            logger.warning('GitHub mirror: close/label of issue #%s incomplete '
                           '(closed=%s labeled=%s)', issue_number, ok, labeled)
        return ok and labeled

    # ---- internals ----

    def _ensure_done_label(self, workdir: str) -> None:
        if self._label_ensured:
            return
        if self._gh(workdir, ['label', 'create', 'done',
                              '--color', '0e8a16',
                              '--force']) is not None:
            self._label_ensured = True

    def _gh(self, workdir: str, args: list[str]) -> subprocess.CompletedProcess | None:
        path = self._gh_path()
        if path is None:
            return None
        try:
            # Fixed executable path, internal argument list.
            out = subprocess.run(  # nosec B603
                [path, *args], cwd=workdir, capture_output=True, text=True,
                timeout=_GH_TIMEOUT,
            )
            return out if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError) as exc:
            logger.info('GitHub mirror: gh %s failed: %s', args[0], exc)
            return None
