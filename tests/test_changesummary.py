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
"""#85 (R38 phase 2): semantic change summary beside the Diff tab."""

import subprocess
from pathlib import Path

from codingdude.changesummary import changed_files, summarize


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(
        ['git', '-c', 'safe.directory=*', *args], cwd=cwd,
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise AssertionError(f'git {args} failed ({r.returncode}): {r.stderr}')


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@t')
    _git(repo, 'config', 'user.name', 't')
    return repo


def test_changed_files_lists_source_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / 'a.py').write_text('def f():\n    pass\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'init')
    (repo / 'a.py').write_text('def f():\n    return 1\n')
    (repo / 'notes.txt').write_text('not source\n')
    assert changed_files(repo) == ['a.py']


def test_summarize_reports_python_symbol_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / 'mod.py').write_text('def gone():\n    pass\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'init')
    (repo / 'mod.py').write_text('def added(x):\n    return x\n')
    out = summarize(repo)
    assert out == [{'path': 'mod.py',
                    'summary': 'removed gone; added added (def added(x))'}]


def test_summarize_reports_js_signature_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / 'app.ts').write_text('function old(): void {}\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'init')
    (repo / 'app.ts').write_text('function fresh(): void {}\n')
    out = summarize(repo)
    assert out and 'removed function old' in out[0]['summary']
    assert 'added function fresh' in out[0]['summary']


def test_summarize_skips_non_source_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / 'README.md').write_text('hi\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'init')
    (repo / 'README.md').write_text('hello\n')
    assert summarize(repo) == []
