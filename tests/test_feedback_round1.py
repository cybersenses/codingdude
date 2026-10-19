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
"""User-feedback round 1 (docs/specs/user-feedback-notes-round1.md):

- Project notes: workdir-scoped, agent-readable, resolvable/clearable.
- HTML artifacts: inline preview payload kind.
- Codegraph auto-bootstrap at run start.
- Platform + contract guidance blocks in instructions.
"""

import json

import pytest
from fastapi.testclient import TestClient

from codingdude.artifacts import ArtifactStore
from codingdude.codegraph_boot import ensure_codegraph_index
from codingdude.db import Database
from codingdude.guidance import contract_block, platform_block
from codingdude.projectnotes import ProjectNoteStore, build_project_notes_toolset


@pytest.fixture()
def db(tmp_path):
    return Database.connect(tmp_path)


# --- T11: project notes -----------------------------------------------------

def test_project_notes_crud_and_workdir_isolation(db):
    store = ProjectNoteStore(db)
    a = store.add('G:\\proj-a', 'agent must ask before fixing')
    store.add('G:\\proj-b', 'always use pnpm here')
    assert store.list('G:\\proj-a') == [
        {'id': a, 'workdir': 'G:\\proj-a', 'content': 'agent must ask before fixing',
         'status': 'open', 'created_at': store.list('G:\\proj-a')[0]['created_at'],
         'resolved_at': None},
    ]
    # resolve hides it from the default listing but keeps it queryable
    store.resolve(a)
    assert store.list('G:\\proj-a') == []
    resolved = store.list('G:\\proj-a', include_resolved=True)
    assert resolved[0]['status'] == 'resolved' and resolved[0]['resolved_at']
    # delete clears for good
    store.delete(a)
    assert store.list('G:\\proj-a', include_resolved=True) == []


def test_project_notes_toolset(db):
    store = ProjectNoteStore(db)
    workdir = 'G:\\proj-a'
    store.add(workdir, 'notes are per-project guidance')
    tools = build_project_notes_toolset(store, workdir).tools

    def call(name, *args, **kwargs):
        import asyncio

        out = tools[name].function(*args, **kwargs)
        return asyncio.run(out) if asyncio.iscoroutine(out) else out

    assert 'per-project guidance' in call('read_project_notes', include_resolved=False)
    out = json.loads(call('add_project_note', 'new guidance'))
    assert store.list(workdir)[-1]['content'] == 'new guidance'
    assert 'resolved' in call('resolve_note', note_id=out['id'])
    remaining = store.list(workdir)
    assert [n['content'] for n in remaining] == ['notes are per-project guidance']


def test_project_notes_endpoints(tmp_path, db):
    from codingdude.server import create_app

    app = create_app(home=tmp_path, token='tok', allow_testclient=True)
    client = TestClient(app)
    headers = {'Authorization': 'Bearer tok'}
    workdir = str(tmp_path / 'proj')
    r = client.post(
        '/notes', json={'workdir': workdir, 'content': 'be terse'},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    note_id = r.json()['id']
    listed = client.get(
        '/notes', params={'workdir': workdir}, headers=headers
    ).json()
    assert [n['content'] for n in listed] == ['be terse']
    assert client.post(
        f'/notes/{note_id}/resolve', headers=headers
    ).status_code == 200
    assert client.get(
        '/notes', params={'workdir': workdir}, headers=headers
    ).json() == []
    assert client.delete(f'/notes/{note_id}', headers=headers).status_code == 200


# --- T14: html artifacts ----------------------------------------------------

def test_emit_html_artifact(db):
    store = ArtifactStore(db, 's1')
    artifact_id = store.emit_html('preview', '<h1>hello</h1>')
    artifact = store._get(artifact_id)
    assert artifact['kind'] == 'html'
    assert json.loads(artifact['payload_json']) == {'html': '<h1>hello</h1>'}


# --- T13: codegraph auto-bootstrap -----------------------------------------

def test_codegraph_boot_runs_init_when_index_missing(tmp_path):
    from types import SimpleNamespace

    calls = []

    def runner(cmd, cwd, timeout=None):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout='ok')

    result = ensure_codegraph_index(
        tmp_path, runner=runner, cli_path='/fake/codegraph',
    )
    assert result == 'ok'
    assert calls and calls[0][-2:] == ['init', str(tmp_path)]


def test_codegraph_boot_skipped_when_indexed(tmp_path):
    (tmp_path / '.codegraph').mkdir()
    calls = []
    result = ensure_codegraph_index(
        tmp_path, runner=lambda cmd, cwd: calls.append(cmd), cli_path='/fake',
    )
    assert result is None and calls == []


def test_codegraph_boot_failure_is_swallowed(tmp_path):
    def boom(cmd, cwd, timeout=None):
        raise RuntimeError('cli exploded')

    assert ensure_codegraph_index(tmp_path, runner=boom, cli_path='/fake') is None


# --- T12: guidance blocks ---------------------------------------------------

def test_platform_block_names_real_platform(tmp_path):
    import platform
    import sys

    block = platform_block(tmp_path)
    assert platform.system() in block
    assert sys.platform in block
    assert str(tmp_path) in block


def test_contract_block_covers_user_feedback_points():
    text = contract_block().lower()
    for phrase in ('evaluate', 'assess', 'wait', 'plan', 'install', 'terse'):
        assert phrase in text
