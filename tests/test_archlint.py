"""R8 tracer: architecture linter with fix-or-waive semantics."""

import textwrap

import pytest

from codingdude.archlint import ArchLint, build_archlint_toolset
from codingdude.db import Database
from codingdude.roadmap import RoadmapStore


def write(workdir, rel, source):
    path = workdir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding='utf-8')


@pytest.fixture()
def workdir(tmp_path):
    d = tmp_path / 'proj'
    (d / 'pkg').mkdir(parents=True)
    return d


@pytest.fixture()
def db(tmp_path):
    return Database.connect(tmp_path / 'home')


def test_private_access_flagged(workdir):
    write(workdir, 'pkg/mod_a.py', '''
        _SECRET = 1

        def _helper():
            return _SECRET
    ''')
    write(workdir, 'pkg/mod_b.py', '''
        from pkg import mod_a

        def leaky():
            return mod_a._SECRET
    ''')
    findings = ArchLint().check(workdir)
    rules = {(f['rule'],) for f in findings if f['rule'] == 'private-access'}
    assert ('private-access',) in rules
    fa = next(f for f in findings if f['rule'] == 'private-access')
    assert 'mod_b.py' in fa['locations'][0]


def test_own_module_private_use_not_flagged(workdir):
    write(workdir, 'pkg/solo.py', '''
        _SECRET = 1

        def ok():
            return _SECRET
    ''')
    assert ArchLint().check(workdir) == []


def test_duplicate_body_flagged_with_locations(workdir):
    write(workdir, 'pkg/x.py', '''
        def add(a, b):
            """Add."""
            return a + b
    ''')
    write(workdir, 'pkg/y.py', '''
        def sum2(first, second):
            return first + second
    ''')
    findings = ArchLint().check(workdir)
    dup = [f for f in findings if f['rule'] == 'duplicate-body']
    assert len(dup) == 1
    assert len(dup[0]['locations']) == 2


def test_different_bodies_not_flagged(workdir):
    write(workdir, 'pkg/x.py', '''
        def add(a, b):
            return a + b
    ''')
    write(workdir, 'pkg/y.py', '''
        def concat(a, b):
            return a + b + a
    ''')
    assert ArchLint().check(workdir) == []


def test_fingerprint_stable(workdir):
    write(workdir, 'pkg/a.py', '''
        _X = 1
    ''')
    write(workdir, 'pkg/b.py', '''
        from pkg import a

        def f():
            return a._X
    ''')
    first = ArchLint().check(workdir)[0]['fingerprint']
    second = ArchLint().check(workdir)[0]['fingerprint']
    assert first == second and first


def test_waive_suppresses_and_records_decision(workdir, db):
    write(workdir, 'pkg/a.py', '''
        _X = 1
    ''')
    write(workdir, 'pkg/b.py', '''
        from pkg import a

        def f():
            return a._X
    ''')
    lint = ArchLint(db=db, workdir=str(workdir))
    finding = lint.check(workdir)[0]
    lint.waive(finding['fingerprint'], 'transitional, cleanup ticket exists')
    result = lint.check(workdir)
    active = [f for f in result if f['rule'] == 'private-access' and not f.get('waived')]
    assert active == []
    waived = [f for f in result if f.get('waived')]
    assert len(waived) == 1
    decisions = RoadmapStore(db).list_decisions(str(workdir))
    assert any(waived[0]['fingerprint'] in d['title'] for d in decisions)


def test_clean_report(workdir):
    write(workdir, 'pkg/fine.py', '''
        def only():
            return 1
    ''')
    report = ArchLint().report(workdir)
    assert 'clean' in report.lower()


async def test_toolset_round_trip(workdir, db):
    write(workdir, 'pkg/a.py', '''
        _X = 1
    ''')
    write(workdir, 'pkg/b.py', '''
        from pkg import a

        def f():
            return a._X
    ''')
    tools = build_archlint_toolset(workdir, ArchLint(db=db, workdir=str(workdir))).tools
    report = await tools['arch_lint'].function()
    assert 'private-access' in report
    fp = ArchLint(db=db, workdir=str(workdir)).check(workdir)[0]['fingerprint']
    out = await tools['waive_finding'].function(fp, 'waived deliberately')
    assert 'waived' in out.lower()
    final = await tools['arch_lint'].function()
    assert 'fix this or waive' not in final and 'WAIVED' in final


def test_missing_contract_flagged_under_src(workdir):
    """R8 thickener: contract-first — public functions under src/ need a
    docstring contract."""
    write(workdir, 'src/pkg/mod.py', '''
        def public_api():
            return 1
    ''')
    findings = ArchLint().check(workdir)
    contract = [f for f in findings if f['rule'] == 'missing-contract']
    assert len(contract) == 1
    assert 'mod.py' in contract[0]['locations'][0]
    assert 'public_api' in contract[0]['locations'][0]


def test_documented_public_api_not_flagged(workdir):
    write(workdir, 'src/pkg/mod.py', '''
        def public_api():
            """Contract: returns one."""
            return 1


        class Widget:
            """Contract: a thing."""

            def helper(self):
                return 2
    ''')
    assert ArchLint().check(workdir) == []


def test_private_and_outside_src_not_contract_checked(workdir):
    """The contract rule only applies to public code under src/."""
    write(workdir, 'pkg/mod.py', '''
        def undocumented():
            return 1
    ''')
    write(workdir, 'src/pkg/inner.py', '''
        def _private():
            return 'different'
    ''')
    assert ArchLint().check(workdir) == []


def test_missing_contract_waivable(workdir, db):
    write(workdir, 'src/pkg/mod.py', '''
        def public_api():
            return 1
    ''')
    lint = ArchLint(db=db, workdir=str(workdir))
    findings = lint.check(workdir)
    assert not findings[0].get('waived')
    lint.waive(findings[0]['fingerprint'], 'transitional seam')
    assert all(f.get('waived') for f in lint.check(workdir))


def test_stale_waiver_reported_for_retirement(workdir, db):
    """ADR hygiene: a waiver whose finding is fixed should be retired."""
    write(workdir, 'src/pkg/mod.py', '''
        def public_api():
            """Contract: fine."""
            return 1
    ''')
    lint = ArchLint(db=db, workdir=str(workdir))
    lint.waive('deadbeef0000', 'finding that no longer exists')
    report = lint.report(workdir)
    assert 'stale-waiver' in report
    assert 'deadbeef0000' in report


async def test_wired_into_build_all(tmp_path, monkeypatch):
    """Upstream check: arch_lint reaches a real engine toolset."""
    from codingdude.config import Config
    from codingdude.plugins import PluginContext, build_all

    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr('codingdude.mcp_config.ensure_default_mcp', lambda *_: None)
    monkeypatch.setattr('codingdude.plugins.merged_mcp_server_names', lambda *_: [])
    ctx = PluginContext(
        workdir=tmp_path, config=Config.defaults(), db=Database.connect(home),
        session_id='s8', home=home,
    )
    toolsets = await build_all(ctx)
    names = {t.name for ts in toolsets for t in getattr(ts, 'tools', {}).values()}
    assert {'arch_lint', 'waive_finding'} <= names
