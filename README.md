# CodingDude

A personal, single-user coding agent built with [pydantic-ai](https://ai.pydantic.dev/), driven from a web UI, with tiered approvals for risky actions.

## Status

Tickets 01–09, 11–13, 15 complete (62 tests, mypy clean): engine with scripted-model test harness, failover (incl. GLM coding-plan endpoint), file tools + surgical edits, shell with approval tiers, session lifecycle (AGENT.md, compaction), delegation, web tools, AST navigation, web server + per-run worker subprocess + SSE + React shell (`codingdude serve`), memory store, budget cap, git/gh tiered tools. Remaining: 10 (approval cards + panels), 14 (MCP), 16 (embeddings), 17 (durable-exec spike). See `.scratch/codingdude/`.

## Run

```bash
uv run codingdude run "task"            # headless (exit 0 ok / 2 gate / 3 budget)
uv run codingdude serve                 # web UI on http://127.0.0.1:8765
```

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
