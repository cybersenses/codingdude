# Reference

Up: [User Manual](../USER-MANUAL.md) · Back to [Quickstart](quickstart.md)

## Security posture

- The server binds **127.0.0.1 only** — it is not reachable from the
  network.
- Browsers on the same origin log in passwordlessly (`POST /auth/local`
  issues a session cookie). Any other client authenticates with the token
  from `~/.codingdude/server-token`: `Authorization: Bearer <token>`, the
  cookie, or `?token=` for `EventSource` streams. `POST /login` also accepts
  the token as a password.
- The token persists across restarts — workers and logged-in browsers never
  re-authenticate.
- Provider keys are never displayed back by the UI or API (presence only).
- Subprocess environments are scrubbed of `KEY`/`TOKEN`/`SECRET`/
  `PASSWORD`/`CREDENTIAL` variables before the agent runs a command; keys
  are never printed.
- All file tools are confined to the session's workdir; path escapes are
  rejected.

## CLI commands

`codingdude --help` lists them; `codingdude --version` prints the version.

### `codingdude run "task"` — headless one-shot

| Option | Purpose |
|---|---|
| `--workdir <dir>` | project directory (default: current) |
| `--model provider:model` | model override for this run |
| `--yolo` | auto-approve every gated action (scripting; headless otherwise fails safe) |
| `--budget <usd>` | hard spend cap for the run |
| `--fix-loop` | run tests after the task and feed failures back (max 3 rounds) |

Exit codes: **0** finished · **1** failed · **2** a gated action needed
approval (the command is printed) · **3** budget exceeded.

### `codingdude serve` — web server + UI

`--port` (default 8765).

### `codingdude restart` — bounce the server

`--port` · `--status` (report PID + health, change nothing) · `--dry-run`
(show what would be bounced). Use after changing CodingDude's own code;
config changes need no restart.

### `codingdude eval` — record and replay scenarios

- Record: `eval --record SESSION_ID --name flow --out scenarios/flow.json`
  (`--check name`, repeatable, attaches checks).
- Replay: `eval --scenarios scenarios/ --workdir .` — exit 0 only when every
  declared check passes.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| 401 on API calls | Wrong/absent token. Browsers: reload the UI; scripts: `Authorization: Bearer <token>` from `~/.codingdude/server-token`. |
| Provider key rejected at run start | **Verify keys** in the Config panel catches bad keys before a run. Coding-plan Z.AI keys need `fallback_base_url` (see [Configuration › example 2](configuration.md#2-zai-glm-coding-plan)). |
| Run "still working" forever | Worker watchdog fixed this class; if seen, check `~/.codingdude/logs/server.log` and `worker-*.log`. |
| New code/fix not in the UI | The server serves the built frontend from `frontend/dist`; rebuild after frontend changes. Compare the `ui`/`srv` versions+timestamps in the StatusFooter; hard-refresh the browser (cached bundles are a classic). |
| Model errors at run start | Check the Config panel warnings and the provider's endpoint/plan. |
| Drive-relative path rejected | Use `G:\path`, not `G:path`. |
| Config edits not taking effect | They apply from the **next run**, not the live one. CodingDude's own code changes need `codingdude restart`. |
| Agent edits the wrong project | The session is bound to a workdir — check the StatusFooter; a ⚠ there means the session is not in the selected project. |

## Where things live

| Path | Contents |
|---|---|
| `~/.codingdude/` (`CODEDUDE_HOME`) | `config.toml`, `server-token`, `mcp.json`, `skills/`, `DIRECTIVES.md`, SQLite DBs, `traces/`, `prompts/`, `uploads/`, `logs/` |
| `<project>/` | your code, ROADMAP.md, CONTEXT.md, AGENT.md, .codegraph/ index, .codingdude/mcp.json, optional .codingdude.toml |
| `<project>/.codingdude.toml` | per-project shell and `[models]` overrides ([Configuration](configuration.md#per-project-overrides-codingdudetoml)) |
