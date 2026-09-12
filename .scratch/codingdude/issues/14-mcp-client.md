# 14: MCP client

**What to build:** External tools via MCP: the global config merges with the per-project config (project wins) at Session start; configured servers' tools load into the agent's toolset; a tool-manager UI lists what's attached and lets you disable servers/tools; tool search kicks in as the toolset grows so prompt cache and model attention survive scale.

**Blocked by:** 09 (React shell)

**Status:** resolved — MCP client loads, merges, and works end-to-end

- [x] A configured MCP server's tools appear in the agent and in the manager UI
- [x] Project config overrides global for the same server; both apply otherwise
- [x] Disabling a server/tool in the UI removes it from subsequent runs
- [x] With a toolset above the threshold, tool search activates and scripted runs still find and use the right tools

2026-09-08: Resolved. Commits 51b4246 + eb70834. Config: `~/.codingdude/mcp.json` (global) merged with `<workdir>/.codingdude/mcp.json` (project wins per server name), Claude-Desktop `mcpServers` shape + CodingDude `disabled` extension. Engine attaches prefixed toolsets per run via pydantic-ai's `load_mcp_toolsets`; the model sees tools as `<server>_<tool>`. Manager UI: new MCP tab (list servers, enable/disable — persisted to the project config). Tool search: delegated to pydantic-ai's toolset machinery (ToolSearch capability auto-injects at scale). Proven end-to-end against a real fastmcp stdio server (tests/mcp_echo_server.py): the model called the prefixed echo tool and got the server's answer.
