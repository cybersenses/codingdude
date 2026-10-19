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
"""First-class planning data (R4): store CRUD, server endpoints, agent tools."""

import subprocess

import pytest

from codingdude.roadmap import RoadmapStore, build_roadmap_toolset
from codingdude.server import create_app


@pytest.fixture
def store(db):
    return RoadmapStore(db)


def _git_init(path):
    subprocess.run(['git', 'init', '-q'], cwd=path, check=True)
    subprocess.run(['git', 'config', 'user.email', 't@t'], cwd=path, check=True)
    subprocess.run(['git', 'config', 'user.name', 't'], cwd=path, check=True)
    subprocess.run(['git', 'commit', '-q', '--allow-empty', '-m', 'init'], cwd=path, check=True)


def test_roadmap_store_crud_and_scoping(store, tmp_path):
    alpha, beta = str(tmp_path / 'a'), str(tmp_path / 'b')
    rid = store.create_roadmap_item(alpha, 'R4 planning data', 'problem/impact/desired')
    store.create_roadmap_item(beta, 'other project item')

    assert [r['id'] for r in store.list_roadmap(alpha)] == [rid]
    assert store.update_roadmap_item(alpha, rid, status='in_progress') is True
    assert store.list_roadmap(alpha)[0]['status'] == 'in_progress'
    # Cross-project updates must not leak.
    assert store.update_roadmap_item(beta, rid, status='done') is False
    assert store.delete_roadmap_item(alpha, rid) is True
    assert store.list_roadmap(alpha) == []


def test_ticket_close_stamps_head_sha(store, tmp_path):
    workdir = tmp_path / 'repo'
    workdir.mkdir()
    _git_init(workdir)
    tid = store.create_ticket(str(workdir), 'ship it')

    store.update_ticket(str(workdir), tid, status='in_progress')
    row = store.list_tickets(str(workdir))[0]
    assert row['commit_sha'] is None  # only closing stamps a commit

    store.update_ticket(str(workdir), tid, status='done')
    row = store.list_tickets(str(workdir))[0]
    assert row['commit_sha']  # linked to the commit that closed it

    sha = subprocess.run(
        ['git', 'rev-parse', '--short', 'HEAD'], cwd=workdir,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert row['commit_sha'] == sha


def test_ticket_filters_and_edges(store, tmp_path):
    wd = str(tmp_path / 'p')
    a = store.create_ticket(wd, 'first')
    store.create_ticket(wd, 'second', blocked_by=str(a))
    store.update_ticket(wd, a, status='done')

    assert [t['title'] for t in store.list_tickets(wd, status='todo')] == ['second']
    assert [t['title'] for t in store.list_tickets(wd, status='done')] == ['first']
    assert store.list_tickets(wd)[0]['blocked_by'] == str(a)  # done sorts last


def test_decision_crud(store, tmp_path):
    wd = str(tmp_path / 'd')
    did = store.create_decision(wd, 'ADR-1: SQLite for planning', 'survives bounces')
    assert store.list_decisions(wd)[0]['title'].startswith('ADR-1')
    assert store.update_decision(wd, did, body='amended') is True
    assert store.list_decisions(wd)[0]['body'] == 'amended'
    assert store.delete_decision(wd, did) is True


def test_roadmap_toolset_tools(store, tmp_path):
    wd = str(tmp_path / 'tools')
    ts = build_roadmap_toolset(store, wd)
    assert {'list_planning', 'update_roadmap_item', 'create_ticket', 'update_ticket',
            'record_decision'} <= set(ts.tools)


@pytest.mark.asyncio
async def test_roadmap_toolset_flow(store, tmp_path):
    wd = str(tmp_path / 'flow')
    rid = store.create_roadmap_item(wd, 'R1 renders', 'see what the agent rendered')

    tools = build_roadmap_toolset(store, wd).tools

    overview = await tools['list_planning'].function()
    assert 'R1 renders' in overview

    msg = await tools['update_roadmap_item'].function(rid, 'in_progress')
    assert 'in_progress' in msg
    assert await tools['update_roadmap_item'].function(999, 'done') == 'roadmap item R999 not found'

    with pytest.raises(ValueError):
        await tools['update_roadmap_item'].function(rid, 'bogus')


@pytest.mark.asyncio
async def test_roadmap_toolset_prefers_roadmap_md(store, tmp_path):
    """ROADMAP.md is canonical: the agent tools read and update it, not the DB."""
    wd = tmp_path / 'md'
    wd.mkdir()
    (wd / 'ROADMAP.md').write_text(
        '# Roadmap\n\n## R1 — Thing\n**Status:** open\n\nBody one.\n', encoding='utf-8'
    )
    tools = build_roadmap_toolset(store, str(wd)).tools

    overview = await tools['list_planning'].function()
    assert '[open] #R1 Thing' in overview

    msg = await tools['update_roadmap_item'].function('R1', 'done')
    assert 'R1 → done' in msg
    text = (wd / 'ROADMAP.md').read_text(encoding='utf-8')
    assert '**Status:** done' in text and 'Thing' in text

    # Accepts bare numeric ids too, and reports unknown items.
    assert 'R1 → in_progress' in await tools['update_roadmap_item'].function(1, 'in_progress')
    assert await tools['update_roadmap_item'].function('R9', 'done') == \
        'roadmap item R9 not found in ROADMAP.md'

    await tools['record_decision'].function('ADR-1', 'store planning in SQLite')
    assert 'ADR-1' in await tools['list_planning'].function()


@pytest.mark.asyncio
async def test_toolset_create_roadmap_item(store, tmp_path):
    """R20: the agent must be able to create roadmap items (the missing tool)."""
    wd = tmp_path / 'create'
    wd.mkdir()
    (wd / 'ROADMAP.md').write_text(
        '# Roadmap\n\n## R1 — First\n**Status:** open\n\nBody.\n', encoding='utf-8'
    )
    tools = build_roadmap_toolset(store, str(wd)).tools
    assert 'create_roadmap_item' in tools

    msg = await tools['create_roadmap_item'].function('Second thing', 'why it matters')
    assert 'R2' in msg
    text = (wd / 'ROADMAP.md').read_text(encoding='utf-8')
    assert '## R2 — Second thing' in text and '**Status:** open' in text
    assert 'why it matters' in text


@pytest.mark.asyncio
async def test_toolset_create_ticket_requires_roadmap_item(store, tmp_path):
    """R20 rule: no ticket without a roadmap item, even for stabilization."""
    wd = tmp_path / 'link'
    wd.mkdir()
    (wd / 'ROADMAP.md').write_text(
        '# Roadmap\n\n## R1 — Thing\n**Status:** open\n\nBody.\n', encoding='utf-8'
    )
    tools = build_roadmap_toolset(store, str(wd)).tools

    # Missing roadmap_id → guidance, not a ticket.
    msg = await tools['create_ticket'].function('do stuff')
    assert 'roadmap' in msg.lower()
    assert store.list_tickets(str(wd)) == []

    # Unknown roadmap id → guidance, not a ticket.
    msg = await tools['create_ticket'].function('do stuff', roadmap_id='R9')
    assert 'not found' in msg
    assert store.list_tickets(str(wd)) == []

    # Valid link (bare numeric accepted, normalized) → ticket created.
    msg = await tools['create_ticket'].function('tracer', roadmap_id='1')
    tid = int(msg.split('#')[1].split()[0])
    assert store.list_tickets(str(wd))[0]['id'] == tid
    assert store.list_tickets(str(wd))[0]['roadmap_id'] == 'R1'


def test_ticket_store_accepts_roadmap_id(store, tmp_path):
    """Store-level create_ticket takes an optional roadmap_id (UI / server path)."""
    wd = str(tmp_path / 'store')
    tid = store.create_ticket(wd, 't', roadmap_id='R3')
    row = store.list_tickets(wd)[0]
    assert row['id'] == tid and row['roadmap_id'] == 'R3'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))
    app = create_app(home=tmp_path / 'home', token='test-token', allow_testclient=True)
    app.state.port = 8000
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c, app.state.token


def test_planning_endpoints_flow(client, tmp_path):
    c, token = client
    h = {'Authorization': f'Bearer {token}'}
    wd = tmp_path / 'proj'
    wd.mkdir()
    wd = str(wd)

    r = c.post('/planning/roadmap', params={'workdir': wd}, json={'title': 'R4'}, headers=h)
    assert r.status_code == 200
    rid = r.json()['id']

    r = c.put(f'/planning/roadmap/{rid}', params={'workdir': wd},
              json={'status': 'in_progress'}, headers=h)
    assert r.status_code == 200

    tid = c.post('/planning/tickets', params={'workdir': wd},
                 json={'title': 't1', 'body': 'b'}, headers=h).json()['id']
    c.put(f'/planning/tickets/{tid}', params={'workdir': wd},
          json={'status': 'done'}, headers=h)

    did = c.post('/planning/decisions', params={'workdir': wd},
                 json={'title': 'ADR-1', 'body': 'x'}, headers=h).json()['id']
    c.put(f'/planning/decisions/{did}', params={'workdir': wd},
          json={'body': 'amended'}, headers=h)

    r = c.get('/planning', params={'workdir': wd}, headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data['roadmap'][0]['status'] == 'in_progress'
    assert data['tickets'][0]['status'] == 'done'
    assert data['decisions'][0]['body'] == 'amended'

    # Validation + 404s
    assert c.put(f'/planning/roadmap/{rid}', params={'workdir': wd},
                 json={'status': 'nope'}, headers=h).status_code == 422
    assert c.put('/planning/tickets/999', params={'workdir': wd},
                 json={'status': 'done'}, headers=h).status_code == 404
    assert c.get('/planning', params={'workdir': str(tmp_path / 'missing')},
                 headers=h).status_code == 404

    # Cleanup
    assert c.delete(f'/planning/tickets/{tid}', params={'workdir': wd}, headers=h).json()['deleted']
    assert c.delete(f'/planning/roadmap/{rid}', params={'workdir': wd}, headers=h).json()['deleted']
    assert c.delete(f'/planning/decisions/{did}', params={'workdir': wd}, headers=h).json()['deleted']
    assert c.get('/planning', params={'workdir': wd}, headers=h).json() == {
        'roadmap': [], 'tickets': [], 'decisions': [],
    }


def test_planning_requires_auth(client, tmp_path):
    c, _ = client
    assert c.get('/planning', params={'workdir': str(tmp_path)}).status_code == 401
