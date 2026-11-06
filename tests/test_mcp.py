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
"""MCP: config merge, toolset loading, disabled handling, engine integration."""

import json
import sys
from pathlib import Path

from codingdude.mcp_config import (
    list_mcp_servers,
    load_merged_mcp_toolsets,
    merged_mcp_config,
    merged_mcp_server_names,
    set_mcp_disabled,
    verify_mcp_toolsets,
)

SERVER_CMD = {'command': sys.executable, 'args': [str(Path(__file__).parent / 'mcp_echo_server.py')]}


def marker_server_cmd(marker, **env_extra):
    """Config entry for mcp_marker_server.py: marks each process spawn, with
    optional SLEEP_SECONDS / FAIL_FIRST knobs (see the fixture docstring)."""
    return {
        'type': 'stdio',
        'command': sys.executable,
        'args': [str(Path(__file__).parent / 'mcp_marker_server.py')],
        'env': {'MARKER_FILE': str(marker), **env_extra},
    }


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


def test_ensure_default_mcp_adds_chrome_devtools_with_telemetry_off(home, monkeypatch):
    """npx present -> chrome-devtools seeded via the cmd wrapper, with
    Google's usage-statistics and update checks explicitly disabled (R61)."""
    from codingdude.mcp_config import ensure_default_mcp, merged_mcp_config

    def which(name: str):
        if name == 'npx':
            return 'C:/Program Files/nodejs/npx.CMD'
        return 'C:/bin/codegraph.CMD'

    monkeypatch.setattr('codingdude.mcp_config.shutil.which', which)
    ensure_default_mcp(home)
    entry = merged_mcp_config(home, home)['mcpServers']['chrome-devtools']
    assert entry['command'] == 'cmd'
    assert entry['args'][:2] == ['/c', 'C:/Program Files/nodejs/npx.CMD']
    args = ' '.join(entry['args'])
    assert 'chrome-devtools-mcp@1.12.0' in args  # pinned, not @latest (R76)
    assert '--no-usage-statistics' in args
    assert '--no-update-checks' in args
    assert 'env' not in entry  # no secrets to expand


def test_ensure_default_mcp_skips_zai_vision_without_npx(home, monkeypatch):
    """No npx on PATH -> neither npx-gated server is seeded (codegraph still is)."""
    from codingdude.mcp_config import ensure_default_mcp, merged_mcp_config

    def which(name: str):
        return 'C:/bin/codegraph.CMD' if name == 'codegraph' else None

    monkeypatch.setattr('codingdude.mcp_config.shutil.which', which)
    ensure_default_mcp(home)
    servers = merged_mcp_config(home, home)['mcpServers']
    assert 'codegraph' in servers
    assert 'zai-vision' not in servers
    assert 'chrome-devtools' not in servers  # same npx gate (R61)


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


def test_verify_drops_broken_server_keeps_healthy(home, tmp_path):
    """A flaky MCP spawn must be dropped for the run, never raise."""
    import asyncio

    from codingdude.mcp_config import (
        load_merged_mcp_toolsets,
        merged_mcp_server_names,
        verify_mcp_toolsets,
    )

    # A portable healthy stdio server (the `mcp` package ships with
    # pydantic-ai) + a guaranteed-broken binary. No machine-specific paths.
    healthy_script = (
        "try:\n"
        "    from mcp.server.mcpserver import MCPServer as Server\n"
        "except ImportError:\n"
        "    from mcp.server.fastmcp import FastMCP as Server\n"
        "Server('tiny').run()"
    )
    home.mkdir(parents=True, exist_ok=True)
    (home / 'mcp.json').write_text(
        json.dumps({
            'mcpServers': {
                'healthy': {
                    'type': 'stdio',
                    'command': sys.executable,
                    'args': ['-c', healthy_script],
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
    healthy, _report = asyncio.run(verify_mcp_toolsets(names, toolsets, attempts=1))
    assert len(healthy) == 1  # broken dropped, healthy kept


def test_verify_returns_health_report(home, tmp_path):
    """MCP degradation must be visible to the agent, not just server logs:
    verify_mcp_toolsets also returns a per-server report (name/ok/error)
    that run context turns into an MCP_STATUS trace event + instructions."""
    import asyncio
    import json as _json

    # Same portable healthy stdio server as the verify test above.
    healthy_script = (
        "try:\n"
        "    from mcp.server.mcpserver import MCPServer as Server\n"
        "except ImportError:\n"
        "    from mcp.server.fastmcp import FastMCP as Server\n"
        "Server('tiny2').run()"
    )
    home.mkdir(parents=True, exist_ok=True)
    (home / 'mcp.json').write_text(_json.dumps({
        'mcpServers': {
            'healthy': {
                'type': 'stdio',
                'command': sys.executable,
                'args': ['-c', healthy_script],
            },
            'broken': {
                'type': 'stdio',
                'command': str(tmp_path / 'definitely-missing2.exe'),
                'args': [],
            },
        },
        'disabled': [],
    }), encoding='utf-8')
    names = merged_mcp_server_names(home, tmp_path)
    toolsets = load_merged_mcp_toolsets(home, tmp_path)
    healthy, report = asyncio.run(
        verify_mcp_toolsets(names, toolsets, attempts=1))
    assert len(healthy) == 1
    by_name = {r['name']: r for r in report}
    assert by_name['healthy']['ok'] is True
    assert by_name['broken']['ok'] is False
    assert by_name['broken']['error']  # readable reason, not None


def test_mcp_status_block_lists_dead_servers_only_when_dead():
    from codingdude.plugins import mcp_status_block

    assert mcp_status_block([]) == ''
    assert mcp_status_block([{'name': 'a', 'ok': True, 'error': None}]) == ''
    block = mcp_status_block([
        {'name': 'codegraph', 'ok': False, 'error': 'WinError 2'},
        {'name': 'echo', 'ok': True, 'error': None},
    ])
    assert block.startswith('## MCP Status')
    assert 'codegraph' in block and 'WinError 2' in block
    # healthy servers are never named in the block
    assert 'echo' not in block
    # dead server must be flagged as unavailable this run
    assert 'unavailable' in block


async def test_preflight_spawn_is_reused_by_agent_run(home, workdir, tmp_path):
    """The pre-flight connection must BE the run's connection: one spawn per
    healthy server per run. The old verify-entered-then-closed flow spawned
    every server twice (pre-flight + agent enter), paying npx/interpreter
    startup twice per run."""
    marker = tmp_path / 'spawns.log'
    home.mkdir(parents=True, exist_ok=True)
    (home / 'mcp.json').write_text(json.dumps({
        'mcpServers': {'marker': marker_server_cmd(marker)},
        'disabled': [],
    }), encoding='utf-8')

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

    def pinger(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(tool_name='marker_ping', args={})])
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        return ModelResponse(parts=[TextPart(content=f"{';'.join(returns)} seen")])

    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(prompt='ping the marker server', workdir=workdir, model=scripted(pinger))
    assert 'pong' in outcome.output  # the live session actually answered a tool call
    assert marker.read_text().count('spawn') == 1  # verify's spawn IS the run's spawn


def test_preflight_verifies_servers_concurrently(home, tmp_path):
    """Pre-flight must not serialize server startups: 4 servers sleeping ~1.2s
    each must verify in well under the serial floor (~4 x spawn+sleep+list)."""
    import asyncio
    import time

    marker = tmp_path / 'spawns.log'
    home.mkdir(parents=True, exist_ok=True)
    (home / 'mcp.json').write_text(json.dumps({
        'mcpServers': {
            f'slow-{i}': marker_server_cmd(marker, SLEEP_SECONDS='1.2')
            for i in range(4)
        },
        'disabled': [],
    }), encoding='utf-8')
    names = merged_mcp_server_names(home, tmp_path)
    toolsets = load_merged_mcp_toolsets(home, tmp_path)

    t0 = time.perf_counter()
    healthy, report = asyncio.run(verify_mcp_toolsets(names, toolsets, attempts=1))
    elapsed = time.perf_counter() - t0

    assert len(healthy) == 4
    assert all(r['ok'] for r in report)
    # Generous bound: tolerates CI variance around the ~2-3s parallel path
    # while still failing the serial floor (~4x spawn+sleep+list, 8s+).
    assert elapsed < 7.0, f'serial pre-flight took {elapsed:.2f}s (bound 7.0s)'


def test_verify_retries_and_recovers_fail_first(home, tmp_path):
    """A server whose first spawn dies must still land healthy on retry, and
    the retry must not leak the failed attempt's session (refcount intact)."""
    import asyncio

    marker = tmp_path / 'spawns.log'
    home.mkdir(parents=True, exist_ok=True)
    (home / 'mcp.json').write_text(json.dumps({
        'mcpServers': {'flaky': marker_server_cmd(marker, FAIL_FIRST='1')},
        'disabled': [],
    }), encoding='utf-8')
    names = merged_mcp_server_names(home, tmp_path)
    toolsets = load_merged_mcp_toolsets(home, tmp_path)

    healthy, report = asyncio.run(verify_mcp_toolsets(names, toolsets, attempts=2))
    by_name = {r['name']: r for r in report}
    assert by_name['flaky']['ok'] is True
    assert by_name['flaky']['error'] is None
    assert len(healthy) == 1
    # keep-enter: the verified session stays open for the run's agent to
    # reuse (no second handshake at agent-enter time)
    from codingdude.mcp_config import _find_list_tools
    assert _find_list_tools(healthy[0]).is_running is True
