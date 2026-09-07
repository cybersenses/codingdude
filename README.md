# CodingDude

A personal, single-user coding agent built with [pydantic-ai](https://ai.pydantic.dev/), driven from a web UI, with tiered approvals for risky actions.

## Status

Tickets 01–08 and 15 complete: engine seam with scripted-model test harness, model failover (incl. GLM coding-plan endpoint), file tools + surgical edits with change events, shell tool with Approval tiers + Pattern Approval, session lifecycle (AGENT.md, compaction, cleanup), delegation to read-only subagents, web search/fetch, AST navigation, and the web server + per-run worker subprocess + SSE (AG-UI shape). Next: tickets 09–14, 16–17 (React UI, approval cards, memory, budget cap, git/gh, MCP, embeddings, durable-exec spike). See `.scratch/codingdude/`.

## Setup

```bash
uv sync
export DEEPSEEK_API_KEY=...   # primary + subagent models
export ZAI_API_KEY=...        # failover model
```

## Layout

- `src/codingdude/` — engine, config, SQLite store, CLI
- `tests/` — engine-seam tests (scripted FunctionModel runs against temp Workdirs)
- `CONTEXT.md` — domain glossary
- `docs/adr/` — architecture decisions

## Configuration

`~/.codingdude/config.toml` (created on first use; `CODEDUDE_HOME` overrides the directory):

| Key | Default |
|---|---|
| `models.main` | `deepseek:deepseek-v4-pro` |
| `models.subagent` | `deepseek:deepseek-v4-flash` |
| `models.fallback` | `zai:glm-5.3` |
| `models.fallback_base_url` | *(unset)* — set to `https://api.z.ai/api/coding/paas/v4` for GLM coding-plan keys |
| `shell.default` | `bash` (Git Bash) or `powershell` |

API keys come from the environment: `DEEPSEEK_API_KEY`, `ZAI_API_KEY`.
