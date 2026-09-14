"""MCP server configuration: global config merged with per-project overrides.

Files use the Claude-Desktop `mcpServers` JSON shape plus a CodingDude
extension, `disabled`: a list of server names excluded from runs. The project
file (`<workdir>/.codingdude/mcp.json`) wins per server name over the global
one (`~/.codingdude/mcp.json`).
"""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from pydantic_ai import mcp


def _load_config_file(path: Path) -> dict:
    if not path.exists():
        return {'mcpServers': {}, 'disabled': [], 'enabled': []}
    raw = json.loads(path.read_text(encoding='utf-8'))
    return {
        'mcpServers': raw.get('mcpServers', {}),
        'disabled': raw.get('disabled', []),
        'enabled': raw.get('enabled', []),
    }


def merged_mcp_config(home: Path, workdir: Path) -> dict:
    """Global config overlaid by the project config (project wins per name)."""
    merged = _load_config_file(home / 'mcp.json')
    project = _load_config_file(workdir / '.codingdude' / 'mcp.json')
    merged['mcpServers'].update(project['mcpServers'])
    # Project `enabled` overrides a global `disabled` for that server (M8).
    merged['disabled'] = sorted(
        (set(merged['disabled']) | set(project['disabled'])) - set(project.get('enabled', []))
    )
    return merged


def _default_mcp_servers() -> dict:
    """Known default servers, resolved for this machine (absent binary -> absent entry).

    Windows can't CreateProcess a batch shim (.cmd/.bat) directly — go through cmd.
    """
    servers: dict = {}
    codegraph = shutil.which('codegraph')
    if codegraph:
        args = ['serve', '--mcp']
        command = codegraph
        if codegraph.lower().endswith(('.cmd', '.bat')):
            command, args = 'cmd', ['/c', codegraph, *args]
        servers['codegraph'] = {
            'type': 'stdio',
            'command': command,
            'args': args,
            # The granular graph tools are cheap for agents and complement
            # the single 'explore' tool the vendor enables by default.
            'env': {'CODEGRAPH_MCP_TOOLS': 'explore,search,callers,callees,impact'},
        }
    npx = shutil.which('npx')
    if npx:
        command, npx_args = npx, ['-y', '@z_ai/mcp-server@latest']
        if npx.lower().endswith(('.cmd', '.bat')):
            command, npx_args = 'cmd', ['/c', npx, *npx_args]
        # The Z.AI vision server (GLM coding plan): key referenced via env
        # expansion, never stored in the file. A missing key fails the server
        # at connect; the MCP pre-flight drops it with a warning.
        servers['zai-vision'] = {
            'type': 'stdio',
            'command': command,
            'args': npx_args,
            'env': {'Z_AI_API_KEY': '${ZAI_API_KEY:-}', 'Z_AI_MODE': 'ZAI'},
        }
    return servers


def ensure_default_mcp(home: Path) -> None:
    """Additively seed the global mcp.json with default servers.

    A missing file is created with all available defaults. An existing file
    gets any *missing* known-default server added; existing entries are never
    modified or removed (user edits win).
    """
    path = home / 'mcp.json'
    servers = _default_mcp_servers()
    if not servers:
        return
    if path.exists():
        config = _load_config_file(path)
        new_servers = {name: conf for name, conf in servers.items() if name not in config['mcpServers']}
        if not new_servers:
            return
        config['mcpServers'].update(new_servers)
    else:
        config = {'mcpServers': servers, 'disabled': []}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding='utf-8')


def list_mcp_servers(home: Path, workdir: Path) -> list[dict]:
    config = merged_mcp_config(home, workdir)
    disabled = set(config['disabled'])
    return [
        {'name': name, 'config': conf, 'disabled': name in disabled}
        for name, conf in config['mcpServers'].items()
    ]


def set_mcp_disabled(home: Path, workdir: Path, name: str, disabled: bool) -> bool:
    """Toggle a server in the project config (creating it if needed).
    Returns False if the server name doesn't exist."""
    config = merged_mcp_config(home, workdir)
    if name not in config['mcpServers']:
        return False

    project_path = workdir / '.codingdude' / 'mcp.json'
    project = _load_config_file(project_path)
    disabled_set = set(project['disabled'])
    enabled_set = set(project.get('enabled', []))
    if disabled:
        disabled_set.add(name)
        enabled_set.discard(name)
    else:
        # Project-level enable overrides a global disable (self-review M8).
        disabled_set.discard(name)
        enabled_set.add(name)
    project['disabled'] = sorted(disabled_set)
    project['enabled'] = sorted(enabled_set)
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text(json.dumps(project, indent=2), encoding='utf-8')
    return True


def load_merged_mcp_toolsets(home: Path, workdir: Path) -> list:
    """Toolsets for every enabled MCP server; empty list when none configured.

    The merged config is written to a temp file for pydantic-ai's loader,
    which speaks the same mcpServers JSON shape. Spawn happens lazily at
    agent enter time, so a broken server would otherwise kill the run
    mid-flight — see `verify_mcp_toolsets`.
    """
    config = merged_mcp_config(home, workdir)
    enabled_servers = {
        name: conf
        for name, conf in config['mcpServers'].items()
        if name not in config['disabled']
    }
    if not enabled_servers:
        return []
    merged = {'mcpServers': enabled_servers}
    digest = hashlib.sha256(json.dumps(merged, sort_keys=True).encode()).hexdigest()[:16]
    tmp = Path(tempfile.gettempdir()) / f'codingdude-mcp-{digest}.json'
    tmp.write_text(json.dumps(merged), encoding='utf-8')
    return mcp.load_mcp_toolsets(tmp)


def _find_list_tools(obj, depth: int = 0):
    """The inner toolset that speaks `list_tools` (PrefixedToolset wraps it)."""
    if hasattr(obj, 'list_tools'):
        return obj
    if depth > 6:
        return None
    for value in getattr(obj, '__dict__', {}).values():
        found = _find_list_tools(value, depth + 1)
        if found is not None:
            return found
    return None


async def verify_mcp_toolsets(names: list[str], toolsets: list, attempts: int = 2) -> list:
    """Pre-flight every MCP server: connect, list tools, retry once.

    A server that can't initialize is dropped for this run with a warning
    instead of raising mid-run — before this, one flaky codegraph spawn
    killed the whole run before the agent could do anything about it.
    """
    import logging

    healthy: list = []
    for name, toolset in zip(names, toolsets, strict=False):
        inner = _find_list_tools(toolset)
        ok = False
        last_exc: Exception | None = None
        for _attempt in range(max(1, attempts)):
            try:
                if inner is None:
                    ok = True  # nothing to verify; keep it
                    break
                async with inner:
                    await inner.list_tools()
                ok = True
                break
            except Exception as exc:  # noqa: BLE001 — spawn failures are expected flakiness
                last_exc = exc
        if ok:
            healthy.append(toolset)
        else:
            logging.getLogger(__name__).warning(
                'MCP server %s failed to initialize (%s); disabled for this run',
                name, last_exc,
            )
    return healthy


def merged_mcp_server_names(home: Path, workdir: Path) -> list[str]:
    """Enabled server names in the same order load_merged_mcp_toolsets yields."""
    config = merged_mcp_config(home, workdir)
    return [
        name for name in config['mcpServers']
        if name not in config['disabled']
    ]
