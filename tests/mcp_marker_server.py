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
"""A minimal MCP stdio server for spawn-count and pre-flight-timing tests.

Each process start appends one `spawn\\n` line to MARKER_FILE (config env),
optionally sleeping SLEEP_SECONDS first (pre-flight concurrency test) and
exiting 1 on the very first start when FAIL_FIRST is set (retry test).
"""

import os
import sys
import time

from fastmcp import FastMCP

mcp = FastMCP('marker-server')

marker = os.environ.get('MARKER_FILE', '')
sleep_seconds = float(os.environ.get('SLEEP_SECONDS', '0') or 0)

if sleep_seconds:
    time.sleep(sleep_seconds)
if marker:
    with open(marker, 'a', encoding='utf-8') as f:
        f.write(f'spawn pid={os.getpid()} ppid={os.getppid()}\n')
if os.environ.get('FAIL_FIRST') and marker:
    with open(marker, encoding='utf-8') as f:
        first_spawn = f.read().count('spawn') == 1
    if first_spawn:
        # First-ever start of this config: die so the client's first attempt fails.
        sys.exit(1)


@mcp.tool
def ping() -> str:
    """Return pong, proving the live session answers."""
    return 'pong'


if __name__ == '__main__':
    mcp.run()
