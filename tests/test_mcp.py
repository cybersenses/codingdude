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


def test_ensure_default_mcp_seeds_once_and_preserves_user_config(home, monkeypatch):
    from codingdude.mcp_config import ensure_default_mcp, merged_mcp_config

    monkeypatch.setattr(
        'codingdude.mcp_config.shutil.which', lambda name: 'C:/bin/codegraph.CMD'
    )
    # Fresh home: seeds codegraph with a cmd wrapper for Windows batch shims.
    ensure_default_mcp(home)
    merged = merged_mcp_config(home, home)
    entry = merged['mcpServers']['codegraph']
    assert entry['command'] == 'cmd'
    assert entry['args'][:2] == ['/c', 'C:/bin/codegraph.CMD']
    assert 'CODEGRAPH_MCP_TOOLS' in entry['env']

    # Existing config: user edits win for existing entries; missing known
    # defaults are added additively (never modify or remove existing ones).
    (home / 'mcp.json').write_text(
        '{"mcpServers": {"codegraph": {"command": "custom"}}}', encoding='utf-8'
    )
    ensure_default_mcp(home)
    merged = merged_mcp_config(home, home)['mcpServers']
    assert merged['codegraph'] == {'command': 'custom'}  # user edit preserved
    assert 'zai-vision' in merged  # missing known default added


def test_ensure_default_mcp_adds_zai_vision_with_env_expansion(home, monkeypatch):
    """npx present -> zai-vision seeded; key referenced via ${VAR:-} expansion,
    never stored in the file."""
    from codingdude.mcp_config import ensure_default_mcp, merged_mcp_config

    monkeypatch.setattr('codingdude.mcp_config.shutil.which', lambda name: 'C:/bin/codegraph.CMD')

    def which(name: str):
        if name == 'npx':
            return 'C:/Program Files/nodejs/npx.CMD'
        return 'C:/bin/codegraph.CMD'

    monkeypatch.setattr('codingdude.mcp_config.shutil.which', which)
    ensure_default_mcp(home)
    entry = merged_mcp_config(home, home)['mcpServers']['zai-vision']
    assert entry['command'] == 'cmd'
    assert entry['args'][:2] == ['/c', 'C:/Program Files/nodejs/npx.CMD']
    assert '@z_ai/mcp-server' in ' '.join(entry['args'])
    assert entry['env']['Z_AI_API_KEY'] == '${ZAI_API_KEY:-}'  # expansion token, not a secret
    assert entry['env']['Z_AI_MODE'] == 'ZAI'


def test_ensure_default_mcp_skips_zai_vision_without_npx(home, monkeypatch):
    """No npx on PATH -> zai-vision is not seeded (codegraph still is)."""
    from codingdude.mcp_config import ensure_default_mcp, merged_mcp_config

    def which(name: str):
        return 'C:/bin/codegraph.CMD' if name == 'codegraph' else None

    monkeypatch.setattr('codingdude.mcp_config.shutil.which', which)
    ensure_default_mcp(home)
    servers = merged_mcp_config(home, home)['mcpServers']
    assert 'codegraph' in servers
    assert 'zai-vision' not in servers


def test_ensure_default_mcp_preserves_existing_zai_vision(home, monkeypatch):
    """A user-modified zai-vision entry is never overwritten."""
    from codingdude.mcp_config import ensure_default_mcp, merged_mcp_config

    monkeypatch.setattr('codingdude.mcp_config.shutil.which', lambda name: 'C:/bin/codegraph.CMD')
    home.mkdir(parents=True, exist_ok=True)
    (home / 'mcp.json').write_text(
        json.dumps({'mcpServers': {'zai-vision': {'command': 'my-npx'}}, 'disabled': []}),
        encoding='utf-8',
    )
    ensure_default_mcp(home)
    assert (
        merged_mcp_config(home, home)['mcpServers']['zai-vision'] == {'command': 'my-npx'}
    )


def test_ensure_default_mcp_skips_when_binary_missing(home, monkeypatch):
    from codingdude.mcp_config import ensure_default_mcp, merged_mcp_config

    monkeypatch.setattr('codingdude.mcp_config.shutil.which', lambda name: None)
    ensure_default_mcp(home)
    assert merged_mcp_config(home, home)['mcpServers'] == {}


def test_verify_drops_broken_server_keeps_healthy(home, tmp_path, monkeypatch):
    """A flaky MCP spawn must be dropped for the run, never raise."""
    import asyncio

    from codingdude.mcp_config import (
        load_merged_mcp_toolsets,
        merged_mcp_server_names,
        verify_mcp_toolsets,
    )

    # codegraph (healthy) + a guaranteed-broken binary.
    home.mkdir(parents=True, exist_ok=True)
    (home / 'mcp.json').write_text(
        json.dumps({
            'mcpServers': {
                'codegraph': {
                    'type': 'stdio',
                    'command': 'cmd',
                    'args': ['/c', r'C:\Users\norma\AppData\Local\codegraph\current\bin\codegraph.CMD', 'serve', '--mcp'],
                },
                'broken': {
                    'type': 'stdio',
                    'command': str(tmp_path / 'definitely-missing.exe'),
                    'args': [],
                },
            },
            'disabled': [],
        }),
        encoding='utf-8',
    )
    names = merged_mcp_server_names(home, tmp_path)
    toolsets = load_merged_mcp_toolsets(home, tmp_path)
    healthy = asyncio.run(verify_mcp_toolsets(names, toolsets, attempts=1))
    assert len(healthy) == 1  # broken dropped, codegraph kept
