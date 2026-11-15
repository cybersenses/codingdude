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

from codingdude.db import Database
from codingdude.roadmap import RoadmapStore, build_roadmap_toolset
from codingdude.server import create_app


@pytest.fixture
def store(db):
    return RoadmapStore(db)


_LEGACY_DESIGN_DDL = """
DROP TABLE tech_designs;
CREATE TABLE tech_designs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'superseded')),
    body TEXT NOT NULL DEFAULT '',
    prd_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_LEGACY_PRD_DDL = """
DROP TABLE prds;
CREATE TABLE prds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'sunset')),
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


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


def test_rebuild_refuses_a_table_name_it_did_not_validate(store):
    """The rebuild interpolates table identifiers (SQL has no parameter for
    them), so the [a-z_]+ check is the only thing between a caller mistake and
    arbitrary SQL. Pinned because deleting it would otherwise leave the suite
    green: the rebuild is only reached by an existing database, and every test
    above passes a hard-coded name."""
    with pytest.raises(ValueError, match='refusing to rebuild'):
        store.db._widen_status_check(
            'prds; DROP TABLE tickets', 'CHECK (1)', 'CREATE TABLE x (a)'
        )


def test_a_refused_rebuild_leaves_no_transaction_or_copy_table(store):
    """The column check refuses with a plain Python raise, so it never travels
    through `_Connection.execute`'s rollback shim ? and `_migrate`'"'"'s COMMIT is
    not reached on that path.

    Left open, the `BEGIN IMMEDIATE` would hold a write lock for the life of the
    process (the R57 mode the wrapper exists to prevent) and the half-built
    `<table>_rebuilt` would be committed by any later write on this connection.
    """
    from codingdude.db import _DESIGN_REBUILD_DDL, _DESIGN_STATUS_CHECK

    store.db._conn.executescript(_LEGACY_DESIGN_DDL)
    # A column the rebuild DDL does not declare: the copy would discard it.
    store.db._conn.execute('ALTER TABLE tech_designs ADD COLUMN reviewer TEXT')
    store.db._conn.execute(
        "INSERT INTO tech_designs (workdir, title, status, body, prd_id,"
        " created_at, updated_at, reviewer) VALUES ('w', 'kept', 'approved',"
        " 'body kept', NULL, 'x', 'x', 'priya')"
    )
    store.db._conn.commit()

    with pytest.raises(ValueError, match='would discard it'):
        store.db._widen_status_check(
            'tech_designs', _DESIGN_STATUS_CHECK, _DESIGN_REBUILD_DDL
        )

    assert store.db._conn.in_transaction is False
    leftover = store.db._conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE name = 'tech_designs_rebuilt'"
    ).fetchone()[0]
    assert leftover == 0
    # The refusal left the data exactly as it was, junk column included.
    rows = store.list_designs('w')
    assert [(r['title'], r['body']) for r in rows] == [('kept', 'body kept')]
    assert store.db._conn.execute(
        'SELECT reviewer FROM tech_designs'
    ).fetchone()[0] == 'priya'


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
        'roadmap': [], 'tickets': [], 'decisions': [], 'prds': [], 'designs': [],
    }


def test_planning_requires_auth(client, tmp_path):
    c, _ = client
    assert c.get('/planning', params={'workdir': str(tmp_path)}).status_code == 401


def test_prd_store_crud(store, tmp_path):
    wd = str(tmp_path / 'p')
    pid = store.create_prd(wd, 'Editor revamp', 'REQ-1 dark mode')
    assert store.list_prds(wd)[0]['status'] == 'draft'
    assert store.update_prd(wd, pid, status='active', body='REQ-1..3') is True
    row = store.list_prds(wd)[0]
    assert row['status'] == 'active' and row['body'] == 'REQ-1..3'
    # Cross-project isolation
    assert store.update_prd(str(tmp_path / 'other'), pid, status='sunset') is False
    assert store.delete_prd(wd, pid) is True
    assert store.list_prds(wd) == []


def test_prd_delivered_status_roundtrip(store, tmp_path):
    """#351: a shipped PRD gets a state that says so. Closing a delivered PRD
    out as 'sunset' claims it retired, 'active' claims it is still in flight,
    and 'draft' claims it was never written — all three misdescribe it."""
    wd = str(tmp_path / 'p')
    pid = store.create_prd(wd, 'Editor revamp', 'REQ-1', status='delivered')
    assert store.list_prds(wd)[0]['status'] == 'delivered'
    assert store.update_prd(wd, pid, status='active') is True
    assert store.list_prds(wd)[0]['status'] == 'active'
    assert store.update_prd(wd, pid, status='delivered') is True
    assert store.list_prds(wd)[0]['status'] == 'delivered'


def test_list_prds_orders_by_lifecycle_stage(store, tmp_path):
    """The list reads as a to-do order: what needs writing, what is in flight,
    what shipped, what was retired. The expected order comes from the PRD
    lifecycle, not from the ordering SQL it exercises."""
    wd = str(tmp_path / 'p')
    for status in ('sunset', 'delivered', 'draft', 'active'):
        store.create_prd(wd, f'PRD {status}', '', status=status)
    assert [p['status'] for p in store.list_prds(wd)] == [
        'draft', 'active', 'delivered', 'sunset',
    ]


def test_legacy_prds_table_accepts_delivered(home, store, tmp_path):
    """#351: CREATE TABLE IF NOT EXISTS pins an existing prds CHECK forever, so
    a database created before 'delivered' existed needs an in-place table
    rebuild. Rows, ids and the AUTOINCREMENT sequence must survive it.

    The ids are non-contiguous (1 and 7) on purpose: a rebuild that dropped the
    id column and let AUTOINCREMENT renumber the copy would produce 1 and 2 and
    then hand out 3, so this shape can tell preservation from renumbering — the
    earlier version of this test inserted a single row and could not.
    """
    wd = str(tmp_path / 'p')
    # A pre-#351 prds table, built the way the old schema declared it.
    store.db._conn.executescript(_LEGACY_PRD_DDL)
    for row_id, title in ((1, 'Shipped PRD'), (7, 'Retired PRD')):
        store.db._conn.execute(
            "INSERT INTO prds (id, workdir, title, status, body, created_at,"
            " updated_at) VALUES (?, ?, ?, 'active', 'REQ-1 kept', 'x', 'x')",
            (row_id, wd, title),
        )
    store.db._conn.commit()

    migrated = RoadmapStore(Database.connect(home))  # reopen: migration runs

    rows = migrated.list_prds(wd)
    assert [(r['id'], r['title'], r['body']) for r in rows] == [
        (1, 'Shipped PRD', 'REQ-1 kept'),
        (7, 'Retired PRD', 'REQ-1 kept'),
    ]
    assert migrated.update_prd(wd, 1, status='delivered') is True
    assert [r['status'] for r in migrated.list_prds(wd)] == ['active', 'delivered']
    # The sequence continued past the highest copied id instead of reusing it.
    assert migrated.create_prd(wd, 'Next PRD') == 8


@pytest.mark.parametrize(
    ('table', 'legacy_ddl'),
    [('prds', _LEGACY_PRD_DDL), ('tech_designs', _LEGACY_DESIGN_DDL)],
)
def test_migrated_table_matches_a_fresh_one(
    home, store, tmp_path, table, legacy_ddl
):
    """The rebuild hand-writes each table's DDL, so a column added to `_SCHEMA`
    later could silently be dropped for anyone upgrading from a pre-#351/#352
    database. This compares the rebuilt table against a fresh one, so that
    drift fails here instead of in the field. Both tables are covered because
    #352 moved the rebuild onto a shared seam — a table-agnostic copy is
    exactly the kind of change that can fit one table and miss the other."""
    store.db._conn.executescript(legacy_ddl)
    store.db._conn.commit()
    rebuilt = RoadmapStore(Database.connect(home)).db

    fresh = Database.connect(tmp_path / 'fresh-home')

    def shape(conn):
        # pragma_table_info(?) is parameterizable, unlike PRAGMA
        columns = [
            (r[1], r[2], r[3], r[4], r[5])
            for r in conn.execute(
                'SELECT * FROM pragma_table_info(?)', (table,)
            )
        ]
        # ...but it does not report constraints, and the CHECK is the whole
        # point of the rebuild: a rebuild that installed the *narrow* CHECK
        # would compare equal on columns alone. Normalised DDL covers both.
        ddl = conn.execute(
            'SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',
            (table,),
        ).fetchone()[0]
        # ALTER TABLE ... RENAME re-quotes the table name and drops the space
        # before the closing paren, so normalise those two cosmetic
        # differences rather than pinning SQLite's rendering of them.
        normalised = ' '.join(ddl.replace('"', '').split()).replace(' )', ')')
        return columns, normalised

    assert shape(rebuilt._conn) == shape(fresh._conn)
    # The last word on it: the widened state the ticket exists for is accepted
    # by the rebuilt table and the narrow one is not.
    workdir = str(tmp_path / 'shape-check')
    store = RoadmapStore(rebuilt)
    if table == 'prds':
        assert store.create_prd(workdir, 'p', 'REQ-1', status='delivered')
    else:
        assert store.create_design(workdir, 'd', 'how', status='delivered')
    assert store.list_prds(workdir) + store.list_designs(workdir)




def test_design_store_crud_and_prd_link(store, tmp_path):
    wd = str(tmp_path / 'd')
    pid = store.create_prd(wd, 'PRD', 'REQ-1')
    did = store.create_design(wd, 'TDD: rendering pipeline', 'trace REQ-1', prd_id=pid)
    row = store.list_designs(wd)[0]
    assert row['prd_id'] == pid and row['status'] == 'draft'
    assert store.update_design(wd, did, status='approved') is True
    assert store.list_designs(wd)[0]['status'] == 'approved'
    assert store.delete_design(wd, did) is True


def test_design_delivered_status_roundtrip(store, tmp_path):
    """#352: a design whose work shipped gets a state that says so.

    'approved' would claim it is agreed and still unbuilt, 'superseded' that
    something replaced it, 'draft' that it was never agreed — all three
    misdescribe a design that was built and still describes the build."""
    wd = str(tmp_path / 'd')
    pid = store.create_prd(wd, 'PRD', 'REQ-1')
    did = store.create_design(
        wd, 'TDD: pipeline', 'how', prd_id=pid, status='delivered'
    )
    row = store.list_designs(wd)[0]
    assert row['status'] == 'delivered' and row['prd_id'] == pid
    assert store.update_design(wd, did, status='draft') is True
    assert store.list_designs(wd)[0]['status'] == 'draft'


def test_list_designs_orders_by_lifecycle_stage(store, tmp_path):
    """Same reading order as PRDs: what needs writing, what is agreed, what
    shipped, what was replaced. The expected order comes from the design
    lifecycle, not from the ordering SQL it exercises."""
    wd = str(tmp_path / 'd')
    for status in ('superseded', 'delivered', 'draft', 'approved'):
        store.create_design(wd, f'TDD {status}', '', status=status)
    assert [d['status'] for d in store.list_designs(wd)] == [
        'draft', 'approved', 'delivered', 'superseded',
    ]


def test_legacy_tech_designs_table_accepts_delivered(home, store, tmp_path):
    """#352: the same in-place rebuild as #351, on the table that carries the
    extra `prd_id` column — if the shared copy seam forgot it, the traceability
    link would be silently cut for every design that already exists. Ids are
    non-contiguous (1 and 7) and one prd_id is NULL, so renumbering and a
    dropped column are both distinguishable from a faithful copy."""
    wd = str(tmp_path / 'd')
    store.db._conn.executescript(_LEGACY_DESIGN_DDL)
    for row_id, title, prd in ((1, 'Shipped design', 4), (7, 'Replaced design', None)):
        store.db._conn.execute(
            "INSERT INTO tech_designs (id, workdir, title, status, body, prd_id,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, 'approved', 'as built', ?, 'x', 'x')",
            (row_id, wd, title, prd),
        )
    store.db._conn.commit()

    migrated = RoadmapStore(Database.connect(home))  # reopen: migration runs

    rows = migrated.list_designs(wd)
    assert [(r['id'], r['title'], r['prd_id'], r['body']) for r in rows] == [
        (1, 'Shipped design', 4, 'as built'),
        (7, 'Replaced design', None, 'as built'),
    ]
    assert migrated.update_design(wd, 1, status='delivered') is True
    # approved (design 7) sorts ahead of delivered (design 1): the ladder puts
    # "agreed, not built" before "shipped".
    assert [r['status'] for r in migrated.list_designs(wd)] == ['approved', 'delivered']
    # The sequence continued past the highest copied id instead of reusing it.
    assert migrated.create_design(wd, 'Next design') == 8


@pytest.mark.asyncio
async def test_prd_and_design_agent_tools(store, tmp_path):
    wd = str(tmp_path / 'tools')
    tools = build_roadmap_toolset(store, wd).tools
    assert {'create_prd', 'read_prd', 'update_prd',
            'create_tech_design', 'read_tech_design', 'update_tech_design'} <= set(tools)

    msg = await tools['create_prd'].function('Editor revamp', 'REQ-1 dark mode')
    assert 'PRD #1' in msg

    body = await tools['read_prd'].function(1)
    assert 'REQ-1 dark mode' in body and '[draft]' in body
    assert await tools['read_prd'].function(99) == 'PRD #99 not found'

    await tools['update_prd'].function(1, status='active', body='REQ-1..3')
    assert '[active]' in await tools['read_prd'].function(1)
    assert 'not found' in await tools['update_prd'].function(99, status='sunset')

    with pytest.raises(ValueError):
        await tools['update_prd'].function(1, status='bogus')

    # No fields → guidance, not a bogus 'not found' for an existing row.
    assert 'nothing to update' in await tools['update_prd'].function(1)
    assert 'nothing to update' in await tools['update_tech_design'].function(1)

    msg = await tools['create_tech_design'].function('TDD: pipeline', 'how', prd_id=1)
    assert '#1' in msg and 'PRD #1' in msg
    body = await tools['read_tech_design'].function(1)
    assert 'implements PRD #1' in body
    await tools['update_tech_design'].function(1, status='approved')
    assert '[approved]' in await tools['read_tech_design'].function(1)

    overview = await tools['list_planning'].function()
    assert '# PRDs' in overview and 'Editor revamp' in overview
    assert '# Tech designs' in overview and 'TDD: pipeline' in overview


@pytest.mark.asyncio
async def test_update_prd_tool_accepts_delivered(store, tmp_path):
    """#351 at the agent seam: the tool an agent uses to close a PRD out must
    offer the honest word, and its rejection message must name it."""
    wd = str(tmp_path / 'tools')
    tools = build_roadmap_toolset(store, wd).tools
    await tools['create_prd'].function('Shipped', 'REQ-1')

    assert await tools['update_prd'].function(1, status='delivered') == 'PRD #1 updated'
    assert '[delivered]' in await tools['read_prd'].function(1)

    with pytest.raises(ValueError, match='delivered'):
        await tools['update_prd'].function(1, status='shipped')


@pytest.mark.asyncio
async def test_update_tech_design_tool_accepts_delivered(store, tmp_path):
    """#352 at the agent seam. The agent closes designs out through this tool,
    so it must offer the honest word in its docstring and its rejection
    message — a status the store accepts but the tool refuses would strand the
    agent on the wrong vocabulary."""
    wd = str(tmp_path / 'tools')
    tools = build_roadmap_toolset(store, wd).tools
    await tools['create_tech_design'].function('Shipped design', 'how')

    assert await tools['update_tech_design'].function(1, status='delivered') == \
        'tech design #1 updated'
    assert '[delivered]' in await tools['read_tech_design'].function(1)

    with pytest.raises(ValueError, match='delivered'):
        await tools['update_tech_design'].function(1, status='shipped')


def test_prd_design_endpoints_flow(client, tmp_path):
    c, token = client
    h = {'Authorization': f'Bearer {token}'}
    wd = tmp_path / 'proj'
    wd.mkdir()
    wd = str(wd)

    pid = c.post('/planning/prds', params={'workdir': wd},
                 json={'title': 'PRD', 'body': 'REQ-1'}, headers=h).json()['id']
    did = c.post('/planning/designs', params={'workdir': wd},
                 json={'title': 'TDD', 'body': 'how', 'prd_id': pid}, headers=h).json()['id']

    assert c.put(f'/planning/prds/{pid}', params={'workdir': wd},
                 json={'status': 'active'}, headers=h).status_code == 200
    assert c.put(f'/planning/designs/{did}', params={'workdir': wd},
                 json={'status': 'approved'}, headers=h).status_code == 200

    data = c.get('/planning', params={'workdir': wd}, headers=h).json()
    assert data['prds'][0]['status'] == 'active'
    assert data['designs'][0]['status'] == 'approved'
    assert data['designs'][0]['prd_id'] == pid

    # Validation + 404s
    assert c.post('/planning/prds', params={'workdir': wd},
                  json={'title': 'x', 'status': 'nope'}, headers=h).status_code == 422
    assert c.put('/planning/prds/999', params={'workdir': wd},
                 json={'status': 'active'}, headers=h).status_code == 404
    assert c.put('/planning/designs/999', params={'workdir': wd},
                 json={'status': 'approved'}, headers=h).status_code == 404
    # Empty PUT is a 422, not a bogus 404 for a row that exists.
    assert c.put(f'/planning/prds/{pid}', params={'workdir': wd},
                 json={}, headers=h).status_code == 422
    assert c.put(f'/planning/designs/{did}', params={'workdir': wd},
                 json={}, headers=h).status_code == 422
    # PUT can (re)link the traceability prd_id.
    assert c.put(f'/planning/designs/{did}', params={'workdir': wd},
                 json={'prd_id': pid}, headers=h).status_code == 200
    # Unknown id on DELETE is a 404.
    assert c.delete('/planning/prds/999', params={'workdir': wd},
                    headers=h).status_code == 404

    # Deleting a PRD severs — not dangles — linked designs' prd_id.
    did2 = c.post('/planning/designs', params={'workdir': wd},
                  json={'title': 'TDD2', 'prd_id': pid}, headers=h).json()['id']
    assert c.delete(f'/planning/prds/{pid}', params={'workdir': wd},
                    headers=h).json()['deleted'] is True
    data = c.get('/planning', params={'workdir': wd}, headers=h).json()
    assert all(d['prd_id'] is None for d in data['designs'])
    assert c.delete(f'/planning/designs/{did}', params={'workdir': wd},
                    headers=h).json()['deleted'] is True
    assert c.delete(f'/planning/designs/{did2}', params={'workdir': wd},
                    headers=h).json()['deleted'] is True
    assert c.get('/planning', params={'workdir': wd}, headers=h).json()['prds'] == []


def test_prd_delivered_status_endpoint(client, tmp_path):
    """#351 at the HTTP seam: the UI's status select must be able to send
    'delivered', and an unknown status must still be refused with a 422."""
    c, token = client
    h = {'Authorization': f'Bearer {token}'}
    wd = tmp_path / 'prd-delivered'
    wd.mkdir()
    wd = str(wd)

    pid = c.post('/planning/prds', params={'workdir': wd},
                 json={'title': 'PRD', 'body': 'REQ-1'}, headers=h).json()['id']
    assert c.put(f'/planning/prds/{pid}', params={'workdir': wd},
                 json={'status': 'delivered'}, headers=h).status_code == 200
    assert c.get('/planning', params={'workdir': wd},
                 headers=h).json()['prds'][0]['status'] == 'delivered'
    assert c.post('/planning/prds', params={'workdir': wd},
                  json={'title': 'x', 'status': 'shipped'},
                  headers=h).status_code == 422


def test_design_delivered_status_endpoint(client, tmp_path):
    """The endpoint validates against DESIGN_STATUSES, so the new value must be
    accepted and a PRD-only value ('active') must still be refused — the two
    vocabularies stay distinct even though both now carry 'delivered'."""
    c, token = client
    h = {'Authorization': f'Bearer {token}'}
    wd = tmp_path / 'design-delivered'
    wd.mkdir()
    wd = str(wd)

    did = c.post('/planning/designs', params={'workdir': wd},
                 json={'title': 'TDD', 'body': 'how'}, headers=h).json()['id']
    assert c.put(f'/planning/designs/{did}', params={'workdir': wd},
                 json={'status': 'delivered'}, headers=h).status_code == 200
    assert c.get('/planning', params={'workdir': wd},
                 headers=h).json()['designs'][0]['status'] == 'delivered'
    assert c.post('/planning/designs', params={'workdir': wd},
                  json={'title': 'x', 'status': 'active'},
                  headers=h).status_code == 422
