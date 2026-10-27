# Quickstart — your first hour with CodingDude

Up: [User Manual](../USER-MANUAL.md) · Next: [Tour of the screen](tour.md)

This page walks you from zero to a first completed agent run. Everything here
works on Windows (the primary platform); Linux and macOS use the same
commands.

## 1. Install and start

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Git.

```bash
uv sync                  # create the venv and install CodingDude
uv run codingdude serve  # start the server + web UI (default port 8765)
```

The first start creates `~/.codingdude/` (override with the `CODEDUDE_HOME`
environment variable) containing:

- `config.toml` — model lineup and provider keys (see
  [Configuration](configuration.md))
- `server-token` — the login token (reused across restarts)
- `mcp.json` — MCP server configuration
- `skills/`, `DIRECTIVES.md`, databases and logs as you use them

The server prints its URL and token, e.g.
`codingdude server on http://127.0.0.1:8765 token=xxxx`. It binds
**127.0.0.1 only** — nothing is reachable from the network.

## 2. Log in and configure a model

Open `http://127.0.0.1:8765` in a browser. A local, same-origin page logs in
automatically (a session cookie is issued); any non-browser client uses the
token from `~/.codingdude/server-token`.

Before the first run the agent needs a working model. Open the **Config**
panel (sidebar → Panels, or the command palette) and either:

- store an API key for a built-in provider (DeepSeek, Z.AI, …), or
- add a custom OpenAI-compatible provider (OpenRouter, a local Ollama, …).

Press **verify keys** — one minimal request per provider tells you the key
works before you spend a run discovering otherwise. Full walkthroughs,
including ready-to-paste `config.toml` examples for DeepSeek, the Z.AI GLM
coding plan, OpenRouter and local models, live in
[Configuration](configuration.md).

## 3. Add a project

In the sidebar: set the **Workdir** field to your project folder, click
**+ New project**, give it a name, and save. Adding a project scaffolds the
directory for agent work — `ROADMAP.md`, `CONTEXT.md`, review checklists and
`reference/` dirs — and builds the codegraph symbol index. Any failure is
reported in the UI, never silently skipped.

The project dropdown remembers your projects; the ✕ next to a project
removes it from the list only (files are never touched).

## 4. Run your first task

Click **+ New session**, type a prompt, and send. A good first task is small
and verifiable:

> Add a `--verbose` flag to scripts/report.py that prints each step it takes.
> Run the script before and after to show the difference.

What you will see:

- The run streams live — tool calls, file edits, plan steps, approvals — in
  the Chat panel.
- A **plan** appears first for non-trivial work, for you to approve.
- **Approval cards** appear before anything risky: shell commands, git push,
  package installs, destructive file operations. Choose *Approve once*,
  *Approve pattern* (same command for the rest of the session), or *Deny*.
- Forms may appear mid-run asking you a question (`ask_user`) — answer them
  inline and the run continues.
- The run ends with a terminal event (`RUN_FINISHED`, `RUN_ERROR`,
  `RUN_CANCELLED`); the agent reports what it did **with evidence** — gate
  output it ran, not claims.

The composer above the chat has per-run controls: pick the model slot,
attach an image (PNG/JPEG), tick **suggest** to make agent edits revertable
proposals instead of direct writes, pick a review **checklist** to run, tick
**fix until green** to have the agent loop on test failures after the task,
or tick **yolo** to auto-approve every gated action for this session
(deliberate — red when active). 🔔 toggles desktop notifications for run
finish/wait.

## 5. Review what the agent did

- The **Review changes →** button (top strip) jumps to the **Diff** panel:
  working-tree diff vs HEAD, a symbol-level change summary, and an impact
  graph.
- Cited code (`path:line` or `path:start-end`, in blue) is clickable — it
  opens the file in the editor and highlights the lines.
- Every file edit is checkpointed; the **Trace** panel lists checkpoints
  with a **rewind** button per snapshot.
- If you enabled **suggest** mode, agent edits are proposals you can revert
  from the diff view.

## 6. Stop and restart things

- **Stop** in the chat interrupts the current run (the worker process is
  terminated; the run is recorded as `interrupted`).
- Code changes to CodingDude itself need `uv run codingdude restart`;
  configuration changes do **not** — they apply from the next run.
- If the browser disconnects mid-run, reconnecting resumes the live run; a
  run that finished while you were away replays from history.

## Where to next

- [Tour of the screen](tour.md) — what is on screen and how the workspace is
  arranged
- [Panels reference](panels.md) — every panel in detail
- [Daily workflows](workflows.md) — feature work, reviews, cost control,
  code exploration, headless/CI use
- [Configuration](configuration.md) — the full configuration cookbook
- [Extending](extending.md) — MCP servers, skills, directives
- [Reference](reference.md) — security, CLI commands, troubleshooting
