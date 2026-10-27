# Daily workflows

Up: [User Manual](../USER-MANUAL.md) · Next: [Configuration](configuration.md)

## Feature work, with the receipts

1. Describe the task in a session. For non-trivial work the agent proposes a
   **plan** and tracks it in steps.
2. Approve gated actions as they surface — or pre-authorise a recurring
   command with *Approve pattern*.
3. Watch progress in the **Waterfall** (is it working or stalled?) and
   **Output** (what happened, narrated).
4. When it claims done, check the evidence: gates it ran (pytest, lint,
   build) with output cited. A claim without a run doesn't count — that rule
   binds the agent, and you can hold it to yours.
5. **Review changes →** opens the Diff panel: read the diff and the
   symbol-level summary, then commit (a gated action — the agent asks).

Work worth tracking lands in the **Planning** panel as tickets under a
roadmap item; the agent keeps statuses current and you can too.

## Reviewing and undoing

- **Diff panel** — the whole working tree vs HEAD, plus per-file
  baseline-vs-current views.
- **Trace panel checkpoints** — every edit is snapshotted; **rewind**
  restores the files. Use this when an experiment went wrong.
- **Suggest mode** (composer checkbox) — agent edits become proposals you
  revert from the diff view instead of direct writes. Useful on code you
  don't want touched without review.
- **Checklists** (composer picker) — run a distilled review checklist
  against the project as a dedicated run.

## Keeping cost and context sane

- **Cost panel** — per-model and per-request usage. Add a `[models.pricing]`
  table (see [Configuration](configuration.md#pricing)) and costs show in
  USD.
- **Model selector** (composer) — run throwaway steps on the cheap
  `subagent` model slot instead of `main`.
- **`thinking`** (config) — on models that support it (GLM profiles), a
  lower thinking level is a real cost lever; `off` disables it.
- **`request_limit`** (config, default 500) — caps model requests per run so
  a long session isn't cut off by the library default.
- **Context meter** (sidebar) — above 80 % the next compaction is near;
  compaction summarises history so long sessions keep working.
- **Budget caps** — headless runs: `--budget USD` (hard stop). Delegated
  sub-agents: `[delegation]` ceilings in config. See
  [Configuration](configuration.md#shell-delegation-planning).

## Understanding code before changing it

- **Graph panel with a file open** — call graph, test evidence (which tests
  reference the file, mutation kill rate), and for Python a control-flow
  graph that flags dead code.
- **Graph panel without a file** — architecture map, project structure, and
  the **repo Q&A** box: ask "where is authentication enforced?" and get an
  answer with citations.
- **Ask in chat** — "show me where sessions are authorised" opens the file
  in the editor with the lines highlighted, both for fresh answers and via
  clickable citations in old messages.

## Delegating

The agent can delegate read-only or background work to parallel sub-agents
(reviews, research) using the `subagent` model slot. Per-delegation ceilings
(`[delegation] max_requests`, `max_cost_usd`) abort a runaway sub-agent with
a readable result instead of burning the session budget.

## Memory that survives the session

Facts you state ("in this repo, always run gates via uv") and solutions the
agent proved are banked in **Memory** and recalled by relevance later.
Standing per-project rules belong in **project notes** (Notes panel) or
`AGENT.md` — see [Extending › directives](extending.md#directives).

## Headless and CI

```bash
uv run codingdude run "fix the failing test in tests/test_auth.py" \
    --workdir . --budget 2.00 --fix-loop
```

- `--yolo` auto-approves gated actions (scripting only — headless otherwise
  fails safe with exit 2 when an approval is needed).
- `--fix-loop` runs tests after the task and feeds failures back (max
  3 rounds).
- Exit codes: `0` finished, `1` failed, `2` needs approval (gate-aborted),
  `3` budget exceeded. See
  [Reference › CLI](reference.md#cli-commands).
- **Evals** — record a real session as a scenario
  (`codingdude eval --record SESSION_ID --name my-flow --out scenarios/flow.json
  --check gates-passed`) and replay it later (`codingdude eval --scenarios
  scenarios/`) as a regression check.

## When a run misbehaves

- Stalled? The AgentStrip's `quiet Ns` turns red after ~2 minutes — check
  **Waterfall** for the hung span, then **Stop**.
- **Output** shows the event log per run; **Trace** the raw events.
- Worker and server logs live in `~/.codingdude/logs/` — see
  [Reference › troubleshooting](reference.md#troubleshooting).
