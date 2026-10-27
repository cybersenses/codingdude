# Panels reference

Up: [User Manual](../USER-MANUAL.md) · Next: [Daily workflows](workflows.md)

Every surface below is a dock panel — open it from the sidebar **Panels**
list or the command palette (`Ctrl+Shift+P`). Without a session selected,
session-bound panels show a placeholder.

## Chat

The conversation with the agent. Streams tool calls, plans, diffs and
approvals live. Clickable `path:line` / `path:start-end` citations (blue)
open the cited file in the editor and highlight the lines — this also works
in replayed history. Approval cards, `ask_user` forms and interactive
artifacts render inline. **Stop** interrupts the run.

## Explorer

The workdir file tree. Click a file to open it in the editor.

## Editor

A code editor for workdir files. Highlights lines revealed by clickable
citations or by the agent's `reveal_code` tool. Has a diff toggle; manual
saves are guarded — you are warned before clobbering edits the agent made
while the file was open.

## Diff

The working tree vs `HEAD`: per-file diffs, a symbol-level change summary,
and an impact graph of what the changes touch. Per-file baseline-vs-current
view with an editable editor pane (save is staleness-guarded). This is the
panel the **Review changes →** button opens.

## Graph

Two modes. With a file open in the editor: its **call graph**, **test
evidence** ("trust" — which test files reference it, property tests, and the
mutation kill rate if one has been run), and for Python files a
**control-flow graph** with a function picker (green blocks reachable, red
blocks dead code). Without a file: the **architecture map** (modules as
nodes, imports as edges), the project structure outline, and a **repo Q&A**
box — questions are answered by the agent with file+line citations.

## Planning

Roadmap items, tickets, design decisions, PRDs and tech designs for the
project, with status changes. `ROADMAP.md` in the repo is canonical when
present. This is the same store the agent's planning tools write — you can
add items and move statuses yourself.

## Artifacts

Live interactive artifacts: choice cards, editable spec blocks, decision
records, and rendered HTML pages.

## Notes

Timestamped session notes plus standing **project notes** — the latter are
read by the agent on every run, which makes them the right place for "always
do X in this repo" facts you do not want in a directive.

## Renders

Images found in the workdir (screenshots, previews), newest first. Files
named `*-dark.*` / `*-light.*` or `*-before.*` / `*-after.*` are
automatically paired into side-by-side **Comparisons** — the convention the
agent uses when it renders UI before/after a change. Split into "This
session" and "Earlier".

## Terminal

Run a shell command in the workdir from the UI. Useful for the command the
agent just told you about without leaving the page.

## Output

Per-run event log with a run selector (status per run, colour-coded), plus a
narrated **"tour of this run"** and a **draft design doc** button that sends
the tour to the agent as a prompt.

## Waterfall

Timeline of the selected run's tool calls and gates — seconds per span,
coloured by kind (edit / gate / tool). The fastest way to answer "where did
the time go" or "is it stalled".

## Trace

The raw event trace, colour-coded by type, plus **checkpoints** — file
snapshots taken before edits, each with a **rewind** button.

## Cost

Token and cost usage for the session: requests, input/output tokens, cost,
broken down by model and per request. Models without a configured price show
token counts only — see [Configuration › pricing](configuration.md#pricing).

## Memory

Durable memory entries — facts the agent noted and solutions it banked after
proving them — with scope and origin. You can add and delete entries. These
survive sessions and are recalled by relevance.

## MCP

Configured MCP servers with per-session enable/disable toggles. Config lives
in `~/.codingdude/mcp.json` (global) + `<project>/.codingdude/mcp.json`
(project) — see [Extending](extending.md#mcp-servers).

## Config

The model lineup and provider key editor with key verification — a UI over
`config.toml`. Shows key *presence* only (never values), warns about lineups
that will misbehave (e.g. a Z.AI coding-plan fallback without its endpoint),
and saves as a merge: only fields you change are written. See
[Configuration](configuration.md).

## Standards

The directives editor (always-injected rules), the skills editor
(create/edit/delete skill procedures), and the review checklist.

## Processes

Running and exited processes the agent spawned this session: pid, status,
exit code, background flag, command line.

Next: [Daily workflows](workflows.md)
