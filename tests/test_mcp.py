"""MCP: config merge, toolset loading, disabled handling, engine integration."""

import json
import sys
from pathlib import Path

from codingdude.mcp_config import (
    list_mcp_servers,
    load_merged_mcp_toolsets,
    merged_mcp_config,
    set_mcp_disabled,
)

SERVER_CMD = {'command': sys.executable, 'args': [str(Path(__file__).parent / 'mcp_echo_server.py')]}


def setup_configs(home, workdir):
    home.mkdir(parents=True, exist_ok=True)
    (home / 'mcp.json').write_text(json.dumps({
        'mcpServers': {'echo': SERVER_CMD, 'global-only': SERVER_CMD},
        'disabled': ['global-only'],
    }))
    (workdir / '.codingdude').mkdir(parents=True, exist_ok=True)
    (workdir / '.codingdude' / 'mcp.json').write_text(json.dumps({
        'mcpServers': {'echo': SERVER_CMD},  # project re-declares echo
    }))


def test_merge_project_wins_and_disabled(home, workdir):
    setup_configs(home, workdir)
    config = merged_mcp_config(home, workdir)
    assert set(config['mcpServers']) == {'echo', 'global-only'}
    assert config['disabled'] == ['global-only']

    servers = list_mcp_servers(home, workdir)
    by_name = {s['name']: s for s in servers}
    assert by_name['echo']['disabled'] is False
    assert by_name['global-only']['disabled'] is True


def test_disable_toggle_persists_in_project_config(home, workdir):
    setup_configs(home, workdir)
    assert set_mcp_disabled(home, workdir, 'echo', disabled=True) is True
    assert list_mcp_servers(home, workdir)[0]['disabled'] is True
    # persisted in the project file
    project = json.loads((workdir / '.codingdude' / 'mcp.json').read_text())
    assert 'echo' in project['disabled']

    assert set_mcp_disabled(home, workdir, 'echo', disabled=False) is True
    assert set_mcp_disabled(home, workdir, 'nope', disabled=True) is False


def test_disabled_server_yields_no_toolset(home, workdir):
    setup_configs(home, workdir)
    assert len(load_merged_mcp_toolsets(home, workdir)) == 1  # echo enabled

    set_mcp_disabled(home, workdir, 'echo', disabled=True)
    assert load_merged_mcp_toolsets(home, workdir) == []  # global-only stays disabled


async def test_engine_uses_mcp_tool(home, workdir):
    setup_configs(home, workdir)
    from helpers import scripted
    from pydantic_ai.messages import (
        ModelMessage,
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )

    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    def mcp_caller(messages: list[ModelMessage], info):
        names = sorted(t.name for t in (info.model_request_parameters.function_tools or []))
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[ToolCallPart(tool_name='echo_echo', args={'text': 'ping'})]
            )
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        return ModelResponse(
            parts=[TextPart(content=f"tools={','.join(names)};returns={returns}")]
        )

    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(
        prompt='use the echo tool', workdir=workdir, model=scripted(mcp_caller)
    )
    assert 'echo_echo' in outcome.output  # prefixed tool name visible to the model
    assert 'echo:ping' in outcome.output  # the MCP server actually answered
