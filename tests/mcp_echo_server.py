"""A minimal MCP stdio server for tests: exposes a single `echo` tool."""

from fastmcp import FastMCP

mcp = FastMCP('echo-server')


@mcp.tool
def echo(text: str) -> str:
    """Echo the given text back, prefixed."""
    return f'echo:{text}'


if __name__ == '__main__':
    mcp.run()
