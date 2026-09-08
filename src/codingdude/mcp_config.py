"""MCP server configuration: global config merged with per-project overrides.

Files use the Claude-Desktop `mcpServers` JSON shape plus a CodingDude
extension, `disabled`: a list of server names excluded from runs. The project
file (`<workdir>/.codingdude/mcp.json`) wins per server name over the global
one (`~/.codingdude/mcp.json`).
"""

import json
import tempfile
from pathlib import Path

from pydantic_ai import mcp


def _load_config_file(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding='utf-8'))
    return {'mcpServers': raw.get('mcpServers', {}), 'disabled': raw.get('disabled', [])}


def merged_mcp_config(home: Path, workdir: Path) -> dict:
    """Global config overlaid by the project config (project wins per name)."""
    merged = _load_config_file(home / 'mcp.json')
    project = _load_config_file(workdir / '.codingdude' / 'mcp.json')
    merged['mcpServers'].update(project['mcpServers'])
    merged['disabled'] = sorted(set(merged['disabled']) | set(project['disabled']))
    return merged


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
    if disabled:
        disabled_set.add(name)
    else:
        disabled_set.discard(name)
    project['disabled'] = sorted(disabled_set)
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text(json.dumps(project, indent=2), encoding='utf-8')
    return True


def load_merged_mcp_toolsets(home: Path, workdir: Path) -> list:
    """Toolsets for every enabled MCP server; empty list when none configured.

    The merged config is written to a temp file for pydantic-ai's loader,
    which speaks the same mcpServers JSON shape.
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
    tmp = Path(tempfile.gettempdir()) / f'codingdude-mcp-{abs(hash(json.dumps(merged, sort_keys=True)))}.json'
    tmp.write_text(json.dumps(merged), encoding='utf-8')
    return mcp.load_mcp_toolsets(tmp)
