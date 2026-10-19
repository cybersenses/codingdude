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
"""A minimal MCP stdio server for tests: exposes a single `echo` tool."""

from fastmcp import FastMCP

mcp = FastMCP('echo-server')


@mcp.tool
def echo(text: str) -> str:
    """Echo the given text back, prefixed."""
    return f'echo:{text}'


if __name__ == '__main__':
    mcp.run()
