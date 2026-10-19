# CodingDude — portable distribution

A self-contained copy of CodingDude (agent server + web UI) that can be dropped
onto any Windows machine.

## Install (one time)

1. Install [uv](https://docs.astral.sh/uv/) if you don't have it:
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. Double-click **`setup-codingdude.bat`**.
   - `uv sync` — installs Python 3.12 + all dependencies into `.venv\`
   - rebuilds the web UI if npm/Node is present (otherwise the bundled
     `frontend/dist` is used as-is)
   - seeds `~\.codingdude` (skills, DIRECTIVES.md) from `.codingdude-seed\`
     on first boot if absent — never overwrites files you already own
     the machine has no CodingDude home yet — never overwrites an existing one

## Run

Double-click **`start-codingdude.bat`** (or `start-codingdude.bat 9000` for a
custom port). First run chains into setup automatically. The server listens on
`127.0.0.1:8765` only; closing the server window stops the agent.

## Configure

Edit `~\.codingdude\config.toml` (API keys, models). It is created from
`.codingdude-seed\config.toml` on first setup. `~\.codingdude` also holds the
runtime DB, traces, logs, and any skills you customise — the `.codingdude-seed`
folder in this distribution is the pristine template.

## Layout

| Path | What |
|---|---|
| `src/`, `pyproject.toml`, `uv.lock` | Python package + pinned dependency lock |
| `tests/` | test suite (sanity check: `uv run pytest -q`) |
| `frontend/src` + configs | web UI source |
| `frontend/dist` | pre-built UI (served by the server) |
| `src/codingdude/data/` | bundled resources (checklists, prompts, templates) |
| `reference/research/` | curated research documents |
| `docs/` | project docs |
| `.codingdude-seed/` | template for a fresh `~\.codingdude` home |
| `tools/github-mcp/` | vendored GitHub MCP server binary (MIT; copied to `%USERPROFILE%\tools\github-mcp` by setup) |
| `setup-codingdude.bat` | one-time installer |
| `start-codingdude.bat` | launcher |

## Quality gates

ruff, mypy, pytest, pip-audit etc. are installed **inside the project venv**
by `uv sync` (the `[dependency-groups]` in pyproject.toml) - they are not on
global PATH, so bare `ruff` in another shell will say "not recognized". Run
them via uv from the project folder:

    uv run ruff check src tests
    uv run mypy
    uv run pytest -q

or just: `gates.bat` (runs all three; pass pytest paths to scope it).

## MCP servers

`setup-codingdude.bat` installs everything the MCP layer needs:

- **codegraph** - `npm i -g @colbymchenry/codegraph` (needs Node)
- **github-mcp-server** - vendored binary in `tools/github-mcp/`, copied to
  `%USERPROFILE%\tools\github-mcp\` (skipped if already present)
- **zai-vision** - runs via `npx -y @z_ai/mcp-server` at boot (needs Node and
  `ZAI_API_KEY` in the environment)
- **gh** - GitHub CLI, installed via winget if missing

`~\.codingdude\mcp.json` is seeded from whatever is found on PATH at first
boot. Existing entries are never overwritten - if an old entry is broken
(e.g. points at a missing binary or a stale `cmd /c` wrapper), delete
`mcp.json` and restart the server to re-seed it.
