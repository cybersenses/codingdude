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
"""Bounce the CodingDude server (the agent) in place.

Self-modifying changes — engine/tool wiring, `frontend/dist` rebuilds — only
take effect once the server process is restarted. This module kills the running
server and relaunches the *same* command, detached, so the bounce survives the
death of whatever requested it (a run's worker shares the server's fate: kill
the server and the worker's WebSocket drops mid-run).

Usage:
    python -m codingdude.restart --status      # report PID + health, do nothing
    python -m codingdude.restart --dry-run     # show what would be bounced
    python -m codingdude.restart               # bounce now (spawns a helper)
    python -m codingdude.restart --bounce      # internal: the helper itself

Also exposed as `codingdude restart [--status|--dry-run] [--port N]`.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_PORT = 8765


# --------------------------------------------------------------------------- #
# process discovery (read-only; safe to call any time)
# --------------------------------------------------------------------------- #
def _ps_processes() -> list[dict]:
    """Every process as {pid, cmdline} on Windows (PowerShell CIM)."""
    script = (
        'Get-CimInstance Win32_Process | '
        'Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress'
    )
    out = subprocess.run(
        ['powershell', '-NoProfile', '-Command', script],
        capture_output=True, text=True, timeout=60,
    ).stdout.strip()
    if not out:
        return []
    # Hostile-but-harmless: other processes' command lines can contain raw
    # control characters, which strict JSON parsing rejects (seen on Windows).
    data = json.loads(out, strict=False)
    if isinstance(data, dict):
        data = [data]
    return [
        {'pid': int(d['ProcessId']), 'cmdline': d.get('CommandLine') or ''}
        for d in data if d.get('ProcessId')
    ]


def _proc_processes() -> list[dict]:
    """Every process as {pid, cmdline} on POSIX (via /proc)."""
    procs = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / 'cmdline').read_bytes()
        except OSError:
            continue
        cmdline = raw.replace(b'\x00', b' ').decode(errors='replace').strip()
        procs.append({'pid': int(entry.name), 'cmdline': cmdline})
    return procs


def list_processes() -> list[dict]:
    """Snapshot of processes this session spawned, newest first."""
    return _ps_processes() if os.name == 'nt' else _proc_processes()


def listening_pid(port: int = DEFAULT_PORT) -> int | None:
    """PID of the process LISTENing on 127.0.0.1:<port>, or None."""
    if os.name == 'nt':
        out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if 'LISTENING' not in line.upper():
                continue
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f':{port}'):
                try:
                    return int(parts[-1])
                except ValueError:
                    continue
        return None
    out = subprocess.run(['ss', '-ltnp'], capture_output=True, text=True).stdout
    import re

    for line in out.splitlines():
        if f':{port}' not in line:
            continue
        match = re.search(r'pid=(\d+)', line)
        if match:
            return int(match.group(1))
    return None


def find_server_processes(port: int = DEFAULT_PORT) -> list[dict]:
    """The server process(es): by listening port, else by a `serve` command line."""
    pid = listening_pid(port)
    if pid is not None:
        return [{'pid': pid}]
    return [
        p for p in list_processes()
        if 'codingdude' in p['cmdline']
        and ' serve' in p['cmdline']
        and 'codingdude.worker' not in p['cmdline']
        and 'codingdude.restart' not in p['cmdline']
    ]


def health_ok(port: int = DEFAULT_PORT) -> bool:
    """Return True when the server answers /health within the timeout."""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001 — any failure means "not up yet"
        return False


# --------------------------------------------------------------------------- #
# kill + relaunch
# --------------------------------------------------------------------------- #
def _kill(pid: int) -> None:
    if os.name == 'nt':
        subprocess.run(
            ['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, text=True
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def _repo_root() -> Path:
    import codingdude

    return Path(codingdude.__file__).resolve().parents[2]


def relaunch_argv(port: int = DEFAULT_PORT) -> list[str]:
    """The command that starts the server (module form; import-safe)."""
    return [sys.executable, '-m', 'codingdude.cli', 'serve', '--port', str(port)]


def _spawn_detached(argv: list[str], cwd: Path, log_path: Path) -> int:
    """Start a process that outlives this one (so a bounce can kill its parent)."""
    log = open(log_path, 'a', encoding='utf-8')  # noqa: SIM115 — inherited by the child
    if os.name == 'nt':
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            argv, cwd=str(cwd), stdout=log, stderr=log,
            stdin=subprocess.DEVNULL, creationflags=flags,
        )
    else:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), stdout=log, stderr=log,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    return proc.pid


def bounce(port: int = DEFAULT_PORT, wait: int = 60) -> dict:
    """Kill the server and relaunch it detached. Runs *inside* the helper."""
    repo = _repo_root()
    log_path = repo / '.scratch' / 'agent-restart.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pids = sorted({p['pid'] for p in find_server_processes(port)})
    with open(log_path, 'a', encoding='utf-8') as log:
        log.write(
            f'\n=== bounce {time.strftime("%Y-%m-%d %H:%M:%S")} '
            f'killing {pids} on port {port} ===\n'
        )
    for pid in pids:
        _kill(pid)
    deadline = time.time() + 15
    while time.time() < deadline and listening_pid(port) is not None:
        time.sleep(0.5)
    new_pid = _spawn_detached(relaunch_argv(port), repo, log_path)
    deadline = time.time() + wait
    while time.time() < deadline:
        if health_ok(port):
            return {'killed': pids, 'new_pid': new_pid, 'healthy': True}
        time.sleep(0.5)
    return {'killed': pids, 'new_pid': new_pid, 'healthy': False}


def trigger_restart(port: int = DEFAULT_PORT, delay: int = 5) -> int:
    """Spawn a DETACHED bounce helper (after `delay` s) and return immediately.

    This is the function to call from inside a running agent. The delay lets the
    *calling* run finish and emit its terminal event before the server goes down;
    without it the run dies mid-stream. The helper then kills/relaunches the
    server even as the caller's own worker process is torn down.
    """
    repo = _repo_root()
    log_path = repo / '.scratch' / 'agent-restart.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    code = (
        f'import time; time.sleep({delay}); '
        f'from codingdude.restart import bounce; print(bounce(port={port}))'
    )
    argv = [sys.executable, '-c', code]
    return _spawn_detached(argv, repo, log_path)


def status(port: int = DEFAULT_PORT) -> dict:
    """Human-readable one-screen status of the server and its workers."""
    return {
        'port': port,
        'listening_pid': listening_pid(port),
        'healthy': health_ok(port),
        'servers': find_server_processes(port),
        'relaunch': relaunch_argv(port),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry: restart (or inspect) the local agent server."""
    parser = argparse.ArgumentParser(prog='codingdude.restart')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--bounce', action='store_true', help='internal: do the kill+relaunch')
    parser.add_argument('--dry-run', action='store_true', help='show what would be bounced')
    parser.add_argument('--status', action='store_true', help='report PID + health only')
    parser.add_argument('--wait', type=int, default=60, help='seconds to wait for health')
    args = parser.parse_args(argv)

    if args.bounce:
        result = bounce(port=args.port, wait=args.wait)
        print(json.dumps(result))
        return 0 if result.get('healthy') else 1

    if args.status or args.dry_run:
        print(json.dumps(status(args.port), indent=2))
        return 0

    helper_pid = trigger_restart(args.port)
    print(json.dumps({'bounce_helper_pid': helper_pid, 'port': args.port}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
