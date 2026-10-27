# CodingDude — User Manual

**Version:** matches the running server (`GET /health`) · **License:** AGPL-3.0-or-later · **Owner:** Cyberflex

CodingDude is a **personal, single-user coding agent** that runs on your
machine, works inside a project directory you choose, follows your
conventions, and asks before doing anything risky. It is driven from a **web
UI** or a **headless CLI**, against any LLM provider you configure. Nothing
leaves your machine except the LLM API calls you configured.

It is **not**: multi-user, a hosted service, an IDE replacement, or a model
provider.

Every feature named in this manual exists in the code; where behavior
depends on configuration, the manual says so.

## The manual

Read in order for a guided start, or jump straight to what you need:

| Page | What it covers |
|---|---|
| [Quickstart](manual/quickstart.md) | Install, start, log in, add a project, run your first task, approve and review — the first hour. |
| [Tour of the screen](manual/tour.md) | What is on screen: sidebar, chat, composer, dock panels, footer, command palette, layout presets. |
| [Panels reference](manual/panels.md) | Every panel in detail — what it shows, what it is for, when to use it. |
| [Daily workflows](manual/workflows.md) | Feature work with plans and gates, reviewing and undoing, cost control, code exploration, delegation, memory, headless/CI. |
| [Configuration](manual/configuration.md) | The cookbook: worked `config.toml` examples (DeepSeek, Z.AI coding plan, OpenRouter, local Ollama), full key reference, per-project overrides, pricing. |
| [Extending](manual/extending.md) | MCP servers, skills, directives, checklists. |
| [Reference](manual/reference.md) | Security and login, CLI commands and exit codes, troubleshooting, where things live. |

Start here if you are new: **[Quickstart](manual/quickstart.md)**.
For the architecture behind all of this, see
[TECHNICAL-DESIGN-MANUAL.md](TECHNICAL-DESIGN-MANUAL.md).

