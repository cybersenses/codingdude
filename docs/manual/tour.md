# Tour of the screen

Up: [User Manual](../USER-MANUAL.md) · Next: [Panels reference](panels.md)

CodingDude is a single dockable workspace. Everything you interact with is a
**panel** that can be moved, split, floated or closed — including the file
explorer, the editor and the chat itself.

## The default layout

```
┌──────────┬───────────────────────────┬──────────────────────┐
│ Sidebar  │ AgentStrip (run status)   │  dock panels         │
│          ├───────────────────────────┤  Diff · Graph ·      │
│ project  │ Chat (streaming run)      │  Planning · Terminal │
│ sessions ├───────────────────────────┤  Output · Trace · …  │
│ panels   │ Prompt composer           │                      │
├──────────┴───────────────────────────┴──────────────────────┤
│ StatusFooter                                                │
└─────────────────────────────────────────────────────────────┘
```

- **Sidebar** — project selector, workdir, **+ New project**,
  **+ New session**, the **Panels** list (● open / ○ closed — click to show
  or focus a panel), and your sessions. Each session shows a green pulse dot
  while a run is live and a **context meter** (turns red above 80 % of the
  context window — that is compaction approaching, not an error).
- **AgentStrip** — the run status line above the chat: `agent idle` /
  streaming state, a `quiet Ns` counter (red after ~2 minutes of silence —
  your cue to check the Waterfall or stop the run), and **Review changes →**
  when the working tree has changes.
- **Chat + Prompt composer** — the conversation and its per-run controls
  (model, image attach, suggest, checklist, fix until green, yolo,
  notifications). See [Quickstart §4](quickstart.md#4-run-your-first-task).
- **Dock panels** — Diff, Graph, Planning, Artifacts, Notes, Renders,
  Terminal, Output, Waterfall, Trace, Cost, Memory, MCP, Config, Standards,
  Processes, plus the explorer and editor. Each has its own section in the
  [Panels reference](panels.md).
- **StatusFooter** — active session id and workdir (with a ⚠ warning if the
  session is not in the selected project), UI and server build/version
  stamps (useful when a fix "isn't showing up" — compare the two), the
  light/dark theme toggle, and a live/spawned process counter.

## Arranging the workspace

- **Move panels** by dragging tab headers between groups; drop on any edge
  to split.
- **Resize** by dragging the divider between panels — the grabbable strip is
  wider than the visible line.
- **Float** a panel to keep it above the layout; **pop out** moves it to its
  own OS window (e.g. Cost on a second monitor). "Dock" in the palette
  brings it back. A blocked popout (popup blocker) shows a dismissible
  notice.
- **Command palette** — `Ctrl+Shift+P` (or `Ctrl+K`): show/hide any panel,
  move the active panel left/right/above/below, float/dock, pop out, apply a
  layout **preset** (Default, Debug, Review, Watching), save the current
  arrangement as a named preset, or reset the layout. This is also the
  keyboard-only path for every move.
- **It persists** — the arrangement is saved per browser (debounced) and
  survives reload. A corrupt or future-versioned saved layout falls back to
  the default preset with a notice; panels the current build no longer
  ships are dropped from a restore while keeping the rest.

## The run lifecycle on screen

1. You send a prompt — the chat streams tool calls, plans, diffs and
   approvals as they happen.
2. Gated actions surface as approval cards; questions surface as forms;
   interactive artifacts (choices, editable specs, decisions, HTML pages)
   render inline and also appear in the Artifacts panel.
3. Terminal events (`RUN_FINISHED`, `RUN_ERROR`, `RUN_CANCELLED`) settle the
   run; the Output and Waterfall panels switch to the new run.
4. Re-running while a run is live supersedes it; **Stop** terminates the
   worker.

Next: [Panels reference](panels.md)
