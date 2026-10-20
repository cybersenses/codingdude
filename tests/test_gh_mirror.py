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
"""R53: GitHub issue auto-mirroring of planning items — enforced in code.

The mirror is best-effort: local writes succeed regardless, gh absence skips
with one log line, and mappings persist so closes reach the right issue.
"""

import os  # nosec B404 — stdlib, used only for test token lookup

import pytest

from codingdude.config import load_config
from codingdude.gh_mirror import GitHubMirror
from codingdude.roadmap import RoadmapStore, build_roadmap_toolset


class FakeMirror:
    """In-memory stand-in for the gh CLI boundary (a true system boundary)."""

    def __init__(self, issue_number=55, fail=False):
        self.issue_number = issue_number
        self.fail = fail
        self.created: list[tuple[str, str, str]] = []
        self.closed: list[tuple[str, int]] = []

    def create_issue(self, workdir, title, body):
        if self.fail:
            return None
        self.created.append((workdir, title, body))
        return self.issue_number

    def close_done(self, workdir, issue_number):
        if self.fail:
            return False
        self.closed.append((workdir, issue_number))
        return True


def _mapping(store, kind, local_id):
    row = store.db._conn.execute(
        'SELECT issue_number FROM gh_mirror WHERE kind = ? AND local_id = ?',
        (kind, str(local_id)),
    ).fetchone()
    return row['issue_number'] if row else None


def test_ticket_create_mirrors_and_close_reaches_issue(db, tmp_path):
    wd = str(tmp_path / 'repo')
    mirror = FakeMirror(issue_number=101)
    store = RoadmapStore(db, mirror=mirror)

    tid = store.create_ticket(wd, 'ship feature', 'body text')
    assert mirror.created == [(wd, 'ship feature', 'body text')]
    assert _mapping(store, 'ticket', tid) == 101

    store.update_ticket(wd, tid, status='done')
    assert mirror.closed == [(wd, 101)]


def test_roadmap_db_create_and_done_mirrors(db, tmp_path):
    wd = str(tmp_path / 'repo')
    mirror = FakeMirror(issue_number=7)
    store = RoadmapStore(db, mirror=mirror)

    rid = store.create_roadmap_item(wd, 'R53 mirror', 'convention in code')
    assert _mapping(store, 'roadmap', f'R{rid}') == 7
    store.update_roadmap_item(wd, rid, status='done')
    assert mirror.closed == [(wd, 7)]


@pytest.mark.asyncio
async def test_roadmap_md_path_mirrors(db, tmp_path):
    """ROADMAP.md is canonical for roadmap items; the mirror rides both paths."""
    wd = tmp_path / 'md'
    wd.mkdir()
    (wd / 'ROADMAP.md').write_text(
        '# Roadmap\n\n## R1 — Thing\n**Status:** open\n\nBody.\n', encoding='utf-8'
    )
    mirror = FakeMirror(issue_number=9)
    store = RoadmapStore(db, mirror=mirror)
    tools = build_roadmap_toolset(store, str(wd)).tools

    await tools['create_roadmap_item'].function('Second thing', 'why')
    assert [c[1] for c in mirror.created] == ['Second thing']
    assert _mapping(store, 'roadmap', 'R2') == 9

    await tools['update_roadmap_item'].function('R2', 'done')
    assert mirror.closed == [(str(wd), 9)]


def test_mirror_unavailable_never_blocks_local_writes(db, tmp_path):
    """gh missing / repo unreachable: writes succeed, no mapping, no raise."""
    wd = str(tmp_path / 'repo')
    mirror = FakeMirror(fail=True)
    store = RoadmapStore(db, mirror=mirror)

    tid = store.create_ticket(wd, 'still works')
    assert store.list_tickets(wd)[0]['id'] == tid
    assert _mapping(store, 'ticket', tid) is None
    assert store.update_ticket(wd, tid, status='done') is True
    assert mirror.closed == []


def test_config_can_disable_mirror(home):
    (home).mkdir(parents=True, exist_ok=True)
    (home / 'config.toml').write_text(
        '[models]\nmain = "a:b"\nsubagent = "a:c"\nfallback = "a:d"\n\n'
        '[planning]\ngithub_mirror = false\n',
        encoding='utf-8',
    )
    assert load_config().planning.github_mirror is False

    m = GitHubMirror()
    assert m.available('/anywhere') is False


def test_default_config_enables_mirror(home):
    load_config()  # writes the default config.toml on first use
    assert load_config().planning.github_mirror is True


def test_issue_number_parsed_from_gh_url(monkeypatch, tmp_path):
    m = GitHubMirror()
    m._enabled = True
    monkeypatch.setattr(GitHubMirror, '_available', {str(tmp_path): True})
    calls: list[list[str]] = []

    def fake_gh(workdir, args):
        calls.append(args)
        if args[0] == 'issue' and args[1] == 'create':
            class Out:
                returncode = 0
                stdout = 'https://github.com/o/r/issues/42\n'
            return Out()
        return None

    monkeypatch.setattr(m, '_gh', fake_gh)
    assert m.create_issue(str(tmp_path), 'T', 'B') == 42
    create = next(a for a in calls if a[:2] == ['issue', 'create'])
    assert '--title' in create and '--body-file' in create


def test_no_gh_binary_means_unavailable(monkeypatch, tmp_path):
    m = GitHubMirror()
    m._enabled = True
    monkeypatch.setattr(GitHubMirror, '_available', {})
    monkeypatch.setattr('shutil.which', lambda name: None)
    assert m.available(str(tmp_path)) is False


class _RecordingGh(GitHubMirror):
    """Probe-path regression: gh must never be asked for `remote` (no such
    subcommand); the origin URL comes from git (monkeypatched here)."""

    def __init__(self):
        super().__init__()
        self.calls: list[list[str]] = []

    def _gh_path(self):
        return 'gh'

    def _gh(self, workdir, args):
        self.calls.append(list(args))
        import subprocess as sp
        return sp.CompletedProcess(args, 0, stdout='Logged in', stderr='')


def test_probe_uses_git_for_origin_not_gh(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    mirror = _RecordingGh()
    GitHubMirror._available.pop(str(tmp_path), None)
    monkeypatch.setattr(GitHubMirror, '_git_origin',
                        staticmethod(lambda wd: 'https://github.com/o/r.git'))
    assert mirror.available(str(tmp_path)) is True
    assert not any('remote' in c for c in mirror.calls)
    assert ['auth', 'status'] in mirror.calls
    GitHubMirror._available.pop(str(tmp_path), None)


def test_probe_false_when_origin_not_github(tmp_path, monkeypatch):
    monkeypatch.setattr(GitHubMirror, '_gh_path', staticmethod(lambda: 'gh'))
    monkeypatch.setattr(GitHubMirror, '_git_origin',
                        staticmethod(lambda wd: 'https://gitlab.com/o/r.git'))
    GitHubMirror._available.pop(str(tmp_path), None)
    assert GitHubMirror().available(str(tmp_path)) is False
    GitHubMirror._available.pop(str(tmp_path), None)


def test_server_md_path_create_and_done_mirrors(tmp_path, monkeypatch):
    """Server ROADMAP.md endpoints mirror both create and done transitions."""
    from fastapi.testclient import TestClient

    import codingdude.roadmap as roadmap_mod
    from codingdude.server import create_app

    wd = tmp_path / 'mdrepo'
    wd.mkdir()
    (wd / 'ROADMAP.md').write_text(
        '# Roadmap\n\n## R1 — Thing\n**Status:** open\n\nBody.\n', encoding='utf-8'
    )
    mirror = FakeMirror(issue_number=77)
    monkeypatch.setattr(roadmap_mod, '_default_mirror', mirror)

    token = os.environ.get('TEST_AUTH_TOKEN', 'unit-test-token')  # nosec B105
    home = tmp_path / 'home'
    home.mkdir()
    app = create_app(home=home, token=token, allow_testclient=True)
    with TestClient(app) as c:
        h = {'Authorization': f'Bearer {token}'}
        r = c.post('/planning/roadmap', params={'workdir': str(wd)},
                   json={'title': 'Second'}, headers=h)
        assert r.status_code == 200
        assert [x[1] for x in mirror.created] == ['Second']

        r = c.put(f"/planning/roadmap/{r.json()['id']}",
                  params={'workdir': str(wd)}, json={'status': 'done'}, headers=h)
        assert r.status_code == 200
        assert mirror.closed == [(str(wd), 77)]
