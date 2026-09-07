# 14: MCP client

**What to build:** External tools via MCP: the global config merges with the per-project config (project wins) at Session start; configured servers' tools load into the agent's toolset; a tool-manager UI lists what's attached and lets you disable servers/tools; tool search kicks in as the toolset grows so prompt cache and model attention survive scale.

**Blocked by:** 09 (React shell)

**Status:** ready-for-agent

- [ ] A configured MCP server's tools appear in the agent and in the manager UI
- [ ] Project config overrides global for the same server; both apply otherwise
- [ ] Disabling a server/tool in the UI removes it from subsequent runs
- [ ] With a toolset above the threshold, tool search activates and scripted runs still find and use the right tools
