# coding-agent

## Agent skills

### Issue tracker

The tracker is the local planning store (roadmap items `R#`, tickets
`#N`) surfaced through the planning tools; `gh_mirror` one-way-mirrors
creates and done-transitions to GitHub issues (see
`docs/GITHUB-STRATEGY.md`). The `.scratch/<feature>/` markdown layout in
`docs/agents/issue-tracker.md` applies only to wayfinder maps, not to
project tickets.

### Triage labels

Default five-label vocabulary, label string = role name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Frontend quality gate

UI changes: `cd frontend && npm run lint` must be clean (enforces jsx-no-undef/no-undef —
esbuild does not catch undefined components, which has crashed the UI twice) and
`npm run build` must succeed before commit. See `frontend/eslint.config.mjs`.

### Audience gate (ticket authoring)
Before authoring any ticket or roadmap item, declare its audience in the first body line: `Audience: human` or `Audience: agent`. Human = the user or end-user of generated systems directly benefits (comprehension, control, output). Agent = internal agent improvement. Both are allowed; when they compete, human goes first, and agent-audience tickets must state the human payoff they eventually enable.
