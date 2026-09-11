"""Rename/refactor: rename_symbol across Python (AST) and JS (tree-sitter)."""

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
