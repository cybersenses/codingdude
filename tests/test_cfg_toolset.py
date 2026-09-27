"""Agent tool seam for CFG analysis (#153): analyze_control_flow(path, function)."""

import pytest
from pydantic_ai import ModelRetry

from codingdude.cfg import build_cfg_toolset

DEAD_SRC = "def f():\n    return 1\n    dead = 2\n"


async def call_tool(toolset, name, args):
    tool = toolset.tools[name]
    return await tool.function(**args)


async def test_tool_reports_dead_code(workdir):
    (workdir / 'flow.py').write_text(DEAD_SRC)
    out = await call_tool(
        build_cfg_toolset(workdir), 'analyze_control_flow',
        {'path': 'flow.py', 'function': 'f'},
    )
    assert 'dead = 2' in out
    assert 'unreachable' in out.lower()


async def test_tool_clean_function_reports_fully_reachable(workdir):
    (workdir / 'clean.py').write_text('def g():\n    return 1\n')
    out = await call_tool(
        build_cfg_toolset(workdir), 'analyze_control_flow', {'path': 'clean.py'},
    )
    assert 'no unreachable' in out.lower()


async def test_unknown_function_is_model_retry(workdir):
    (workdir / 'flow.py').write_text(DEAD_SRC)
    with pytest.raises(ModelRetry):
        await call_tool(
            build_cfg_toolset(workdir), 'analyze_control_flow',
            {'path': 'flow.py', 'function': 'nope'},
        )


async def test_missing_path_is_model_retry(workdir):
    with pytest.raises(ModelRetry):
        await call_tool(
            build_cfg_toolset(workdir), 'analyze_control_flow', {'path': 'gone.py'},
        )


async def test_path_escape_is_model_retry(workdir):
    with pytest.raises(ModelRetry):
        await call_tool(
            build_cfg_toolset(workdir), 'analyze_control_flow',
            {'path': '../outside.py'},
        )
