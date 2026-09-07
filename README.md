# CodingDude

A personal, single-user coding agent built with [pydantic-ai](https://ai.pydantic.dev/), driven from a web UI, with tiered approvals for risky actions.

## Status

Ticket 01 (Foundations) complete: package skeleton, config, SQLite persistence, engine seam with a scripted-model test harness, and model failover wiring. See `.scratch/codingdude/` for the spec and tickets.

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
