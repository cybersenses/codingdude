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
"""Rename/refactor: rename_symbol across Python (AST) and JS (tree-sitter)."""

import pytest

from codingdude.deadcode import build_deadcode_toolset  # noqa: F401 (smoke)
from codingdude.refactor import build_refactor_toolset


async def test_rename_python_function_across_files(home, workdir):
    (workdir / 'greet.py').write_text('def greet(name):\n    return name\n')
    (workdir / 'app.py').write_text('from greet import greet\n\nprint(greet("hi"))\n')
    toolset = build_refactor_toolset(workdir)
    tool = toolset.tools['rename_symbol']
    result = await tool.function(old_name='greet', new_name='hello')
    # def + import + call site = 3+ replacements across 2 files
    assert '4' in result or '3' in result
    assert (workdir / 'greet.py').read_text() == 'def hello(name):\n    return name\n'
    app = (workdir / 'app.py').read_text()
    assert 'from greet import hello' in app
    assert 'print(hello("hi"))' in app


async def test_rename_python_class(home, workdir):
    (workdir / 'model.py').write_text('class OldName:\n    pass\n\n\nx = OldName()\n')
    toolset = build_refactor_toolset(workdir)
    await toolset.tools['rename_symbol'].function(old_name='OldName', new_name='NewName')
    assert 'class NewName' in (workdir / 'model.py').read_text()
    assert 'NewName()' in (workdir / 'model.py').read_text()


async def test_rename_js_function(home, workdir):
    (workdir / 'util.js').write_text(
        'function calcTotal(a) { return a; }\nconst out = calcTotal(5);\n'
    )
    toolset = build_refactor_toolset(workdir)
    await toolset.tools['rename_symbol'].function(old_name='calcTotal', new_name='computeTotal')
    content = (workdir / 'util.js').read_text()
    assert 'function computeTotal(a)' in content
    assert 'computeTotal(5)' in content
    assert 'calcTotal' not in content


async def test_rename_not_found_is_retryable(home, workdir):
    from pydantic_ai import ModelRetry

    (workdir / 'x.py').write_text('def something():\n    pass\n')
    toolset = build_refactor_toolset(workdir)
    try:
        await toolset.tools['rename_symbol'].function(old_name='missing', new_name='y')
        raise AssertionError('should have raised')
    except ModelRetry as exc:
        assert 'missing' in str(exc)


async def test_engine_receives_rename_tool(home, workdir):
    from codingdude.refactor import build_refactor_toolset as brt

    toolsets = [brt(workdir)]
    names = sorted(t.name for ts in toolsets for t in ts.tools.values())
    assert 'rename_symbol' in names


async def test_rename_gated_by_approvals(home, workdir):
    """Orphan-toolsets guard: rename_symbol mass-writes files — with an
    interactive policy that denies, nothing is written."""
    from pydantic_ai import ModelRetry, UnexpectedModelBehavior

    from codingdude.approvals import ApprovalPolicy

    (workdir / 'greet.py').write_text('def greet(name):\n    return name\n')

    async def deny(command):
        return 'deny'

    toolset = build_refactor_toolset(workdir, approvals=ApprovalPolicy(ask=deny))
    with pytest.raises((ModelRetry, UnexpectedModelBehavior)):
        await toolset.tools['rename_symbol'].function(old_name='greet', new_name='hello')
    assert 'greet' in (workdir / 'greet.py').read_text()


async def test_rename_gated_headless_aborts(home, workdir):
    """Headless (no ask callback): rename raises GateRequired per ADR-0003."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.tools import GateRequired

    (workdir / 'x.py').write_text('def something():\n    pass\n')
    toolset = build_refactor_toolset(workdir, approvals=ApprovalPolicy())
    with pytest.raises(GateRequired):
        await toolset.tools['rename_symbol'].function(old_name='something', new_name='else')


async def test_rename_emits_edit_events(home, workdir):
    """Every modified file reports one EDIT_APPLIED (kind 'rename') so the
    trace, checkpoints, and UI see mass renames like any other edit."""
    (workdir / 'greet.py').write_text('def greet(name):\n    return name\n')
    events = []
    toolset = build_refactor_toolset(workdir, on_edit=events.append)
    await toolset.tools['rename_symbol'].function(old_name='greet', new_name='hello')
    assert events, 'at least one EDIT_APPLIED expected'
    ev = next(e for e in events if e['path'] == 'greet.py')
    assert ev['type'] == 'EDIT_APPLIED'
    assert ev['kind'] == 'rename'
