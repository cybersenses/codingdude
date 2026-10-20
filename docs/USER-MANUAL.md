# CodingDude — User Manual

**Version:** matches the running server (`GET /health`) · **License:** AGPL-3.0-or-later · **Owner:** Cyberflex

This manual describes CodingDude as shipped. Every feature named here exists in
the code; where behavior depends on configuration, the manual says so.

---

## 1. What CodingDude is

A **personal, single-user coding agent** that runs on your machine, works
inside a project directory you choose, follows your conventions, and asks
before doing anything risky. It is driven from a **web UI** or a **headless
CLI**, against any LLM provider you configure (OpenAI-compatible endpoints or
natively supported providers). Nothing leaves your machine except the LLM API
calls you configured.

It is **not**: multi-user, a hosted service, an IDE replacement, or a model
provider.

## 2. Installation & startup

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Git. Windows is
the primary platform; Linux/macOS work with the same commands.

```bash
uv sync                # create the venv and install CodingDude
uv run codingdude serve          # start the web server (default port 8765)
```

The server prints its URL and login token, e.g.
`codingdude server on http://127.0.0.1:8765 token=xxxx`. The token is stored
in `~/.codingdude/server-token` and reused across restarts — workers and
already-logged-in browsers never re-authenticate. If the frontend was built
(`frontend/dist`), the UI is served from the same port; open the URL in a
browser and log in (see §3.3).

Subcommands (`codingdude --help`):

| Command | Purpose |
|---|---|
| `run` | Headless one-shot run — no web UI. Options: `--workdir`, `--model`, `--yolo`, `--budget` (USD spend cap), `--fix-loop`. (Image attach is web-UI only.) |
| `serve` | Start the web server. `--port` (default 8765). |
| `restart` | Restart a running server. `--port`, `--status` (report PID + health, do nothing), `--dry-run` (show what would be bounced). |
| `eval` | Replay recorded scenarios (`--scenarios`, `--workdir`), or record one from a real session (`--record SESSION_ID --name --out`, `--check` repeatable). |

### 2.1 First boot

On first start, CodingDude creates `~/.codingdude/` (override with the
`CODEDUDE_HOME` environment variable) containing:

- `config.toml` — model lineup and provider keys
- `server-token` — login token
- `mcp.json` — MCP server configuration (seeded automatically)
- `skills/`, `DIRECTIVES.md`, `memory.db` and friends as you use them

## 3. Configuration

### 3.1 Where configuration lives

Everything user-level lives in `~/.codingdude/` (or `CODEDUDE_HOME`). The main
file is `config.toml`:

```toml
[models]
main = "openai:gpt-5-mini"      # primary agent model
subagent = "..."                 # delegated sub-agent runs
fallback = "..."                 # failover when main errors
fallback_base_url = "..."        # e.g. Z.AI coding-plan endpoint
vision = "..."                   # image analysis model (optional)
thinking = "..."                 # reasoning effort, provider-specific
max_tokens = ...
context_limit = ...
request_limit = ...

[providers.myprovider]
api_key = "..."                  # or use env_var below
base_url = "https://.../v1"     # any OpenAI-compatible API
env_var = "MYPROVIDER_API_KEY"   # env var wins over stored api_key
```

You almost never edit this file by hand — the **Config tab** in the UI edits it
for you (see §7.14). Changes apply from the **next run**; no server restart
needed.

### 3.2 Model lineup slots

| Slot | Used for |
|---|---|
| `main` | The primary agent loop |
| `subagent` | Delegated read-only/background sub-agents |
| `fallback` | Automatic failover when the main model errors |
| `vision` | Screenshot/image analysis |

Any `provider:model` string works if `provider` is a configured provider with
a `base_url`, a known native provider, or an env-var-backed provider.

### 3.3 Login & security posture

- The server binds **127.0.0.1 only** — it is not reachable from the network.
- Browsers log in passwordlessly: a local, same-origin page gets a session
  cookie automatically (`POST /auth/local`); any other client uses the token
  (`Authorization: Bearer <token>`, cookie, or `?token=` for EventSource).
- `POST /login` also accepts the token as a password.
- Keys stored in `config.toml` are never displayed back; the UI shows
  presence only, and `/config/verify` smoke-tests each provider's auth.

## 4. Core concepts

| Concept | What it is |
|---|---|
| **Workdir** | The project directory a session works in. All file tools are confined to it. |
| **Session** | A conversation bound to a workdir. Persistent and resumable. |
| **Run** | One agent execution inside a session. Each run is a subprocess with its own trace; re-running supersedes any live previous run. |
| **Approval** | An interactive card asking you to approve/deny a gated action. "Pattern" approval remembers the exact command for the session. |
| **Gate** | Automated check (tests, lint, types, security scan) the agent must pass or account for. |
| **Skill** | A loadable procedure (`SKILL.md`) the agent pulls in when relevant. |
| **Directives** | `~/.codingdude/DIRECTIVES.md` — always-injected user rules, plus per-project `AGENT.md`. |
| **Checkpoint** | A snapshot of files the agent can rewind to. |
| **Artifact** | An interactive card mid-run: choice, editable spec, decision, or rendered HTML. |

## 5. Daily use — web UI

### 5.1 Sessions & projects

1. Add a **project** (name + workdir). Creating a project scaffolds the
   project (ROADMAP.md, CONTEXT.md, checklists, `reference/` dirs) and boots
   the codegraph symbol index; failures are reported, never silent.
2. Create a **session** in that project, type a prompt, optionally pick a
   model / toggle yolo / set a budget / attach an image, and send.
3. Everything the agent does streams live: tool calls, file diffs, approvals,
   plans, artifacts. Terminal events (`RUN_FINISHED`, `RUN_ERROR`,
   `RUN_CANCELLED`) settle the run.

If the browser disconnects mid-run, reconnecting resumes the live run; if the
run finished while you were away, the persisted history replays.

### 5.2 Asking and approving

- Gated actions (shell commands, git push/PR, destructive file ops) surface
  **Approval cards**: Approve once, Approve pattern (same command, rest of
  session), or Deny.
- `ask_user` questions appear as forms you answer inline.
- **Artifacts** let you pick options, edit spec text inline, or view rendered
  HTML pages directly in the panel.

### 5.3 Stop / cancel

The stop button terminates the run's worker process. Runs are recorded with
status `completed` / `interrupted` / `failed`.

### 5.4 Exit codes (headless)

| Exit | Meaning |
|---|---|
| 0 | Run finished |
| 2 | A gated action needed approval (headless fails safe) — or use `--yolo` |
| 3 | Budget cap reached (hard stop, even with `--yolo`) |

## 6. The agent's working rules (what you can rely on)

- **Confined file access.** All file tools resolve inside the session's
  workdir; path escapes are rejected.
- **Ask before risky.** Tiered approvals; pushes/PRs/releases/destructive ops
  are always gated.
- **Evidence over assertion.** The agent runs gates (pytest/ruff/mypy or your
  equivalents, security scans) and cites output; a claim without a run doesn't
  count.
- **Process discipline.** Non-trivial work starts with a plan you approve,
  tracked steps, and a review at the end. Work is tracked in ROADMAP/tickets,
  PRDs, and tech designs (Planning tab).
- **Secrets hygiene.** Subprocess environments are scrubbed of
  KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL variables; keys are never printed.
- **Budget cap.** Set a USD cap per run; the run hard-stops when reached.

## 7. UI reference — right panel tabs

| Tab | What it shows |
|---|---|
| **Diff** | Working-tree diff vs HEAD, symbol-level change summary, impact graph. Per-file baseline-vs-current diff view; editor with save (with staleness guard). |
| **Graph** | Per-file call graph + test-evidence ("trust") report, control-flow graph (green reachable / red dead code); without a file: architecture map (modules as nodes, imports as edges), project structure outline, and repo Q&A with citations. |
| **Planning** | Roadmap items, tickets, design decisions, PRDs, tech designs for the project — add items, change statuses. ROADMAP.md is canonical when present. |
| **Artifacts** | Live interactive artifacts (choice/spec/decision/HTML). |
| **Notes** | Session notes (timestamped) and standing project notes the agent reads every run. |
| **Renders** | Images in the workdir (screenshots, previews), newest first. |
| **Terminal** | Run a shell command in the workdir from the UI. |
| **Output** | Per-run event output; narrated "tour of this run" and a draft design-doc button. |
| **Waterfall** | Timeline of a run's tool calls/gates (seconds per span). |
| **Trace** | Raw event trace and checkpoints (with rewind). |
| **Cost** | Token/cost usage for the session. |
| **Memory** | Persistent memory entries; add/delete. |
| **MCP** | Configured MCP servers; enable/disable per server. |
| **Config** | Model lineup + provider keys editor, with key verification. |
| **Standards** | Directives editor, skills editor (create/edit/delete), review checklist. |

Left panel: sessions list and file explorer (tree, editor with diff toggle —
manual saves are guarded against clobbering concurrent agent edits).

## 8. Extending CodingDude

- **Custom providers** — Config tab or `[providers.name]` in config.toml; any
  OpenAI-compatible API. No code changes.
- **MCP servers** — edit `~/.codingdude/mcp.json` (global) and
  `<project>/.codingdude/mcp.json` (project); merge order global + project;
  toggle servers per session in the MCP tab.
- **Skills** — drop a `SKILL.md` directory in `~/.codingdude/skills/` or the
  project's skills dir; edit them in the Standards tab. Skills load by name on
  demand.
- **Directives** — `~/.codingdude/DIRECTIVES.md` (global) plus project
  `AGENT.md`; layered, always injected.
- **Checklists** — `reference/checklists/*.md` in the repo (also seeded into
  projects), surfaced as invokable actions and in Standards → checklist.

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| 401 on API calls | Wrong/absent token. Browsers: log in at the UI; scripts: `Authorization: Bearer <token>` from `~/.codingdude/server-token`. |
| Run "still working" forever | Fixed by design (worker watchdog); if seen, check `~/.codingdude/logs/server.log`. |
| Model errors at run start | Check the Config tab — provider key verification catches bad keys before a run. |
| New code not in UI | The server serves the built frontend from `frontend/dist`; rebuild after frontend changes. Version mismatch: check `GET /health` (`version`, `git_sha`, `started_at`) vs the UI. |
| Drive-relative path rejected | Use `G:\path` not `G:path` — the server rejects the latter with a hint. |
| Server state stale after edits | `codingdude restart` (or stop/start) — code changes need a restart; config changes do not. |

## 10. Where things live

| Path | Contents |
|---|---|
| `~/.codingdude/` (`CODEDUDE_HOME`) | config.toml, server-token, mcp.json, skills/, DIRECTIVES.md, SQLite DBs, traces/, prompts/, uploads/, logs/ |
| `<project>/` | your code, ROADMAP.md, CONTEXT.md, AGENT.md, .codegraph/ index, .codingdude/mcp.json |
