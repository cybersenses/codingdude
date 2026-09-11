"""Regression tests for self-fix tranche 2 (H3/H4/H8/M2/M6).

Each test fails on the pre-fix code and passes after the fix; they pin the
Workdir boundary and the documented-config behaviours that were broken.
"""

import pytest
from pydantic_ai import ModelRetry

from codingdude.approvals import ApprovalPolicy
from codingdude.config import load_project_config
from codingdude.deadcode import build_deadcode_toolset
from codingdude.tools import build_coverage_toolset, build_toolset


def _fn(toolset, name):
    return toolset.tools[name].function


async def test_h3_run_coverage_rejects_escaping_source(workdir):
    """`source` must stay a relative in-Workdir path (no shell injection)."""
    run_coverage = _fn(build_coverage_toolset(workdir, ApprovalPolicy()), 'run_coverage')
    with pytest.raises(ModelRetry):
        await run_coverage(source='../..')
    with pytest.raises(ModelRetry):
        await run_coverage(source='src/../..')


def test_h4_project_shell_documented_shape(workdir):
    """The documented `shell = "powershell"` form must take effect (issue 04)."""
    (workdir / '.codingdude.toml').write_text('shell = "powershell"\n', encoding='utf-8')
    assert load_project_config(workdir) == {'shell': 'powershell'}


async def test_h8_deadcode_is_workdir_confined(workdir):
    """find_dead_code must refuse paths outside the Workdir."""
    find_dead_code = _fn(build_deadcode_toolset(workdir), 'find_dead_code')
    with pytest.raises(ModelRetry):
        await find_dead_code(path='../../..')


def test_m2_glob_refuses_escaping_pattern(workdir):
    """glob() must refuse patterns that climb out of the Workdir."""
    glob = _fn(build_toolset(workdir, read_only=True), 'glob')
    with pytest.raises(ModelRetry):
        glob('../../*.py')


def test_m6_delete_session_removes_plans(db, workdir):
    """Deleting a Session must not orphan its plans rows."""
    sid = db.create_session(workdir)
    db._conn.execute(
        "INSERT INTO plans (session_id, goal, steps, status, created_at)"
        " VALUES (?, 'g', '[]', 'approved', 'now')",
        (sid,),
    )
    db._conn.commit()
    db.delete_session(sid)
    remaining = db._conn.execute(
        'SELECT COUNT(*) AS c FROM plans WHERE session_id = ?', (sid,)
    ).fetchone()['c']
    assert remaining == 0
