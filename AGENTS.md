# coding-agent

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-label vocabulary, label string = role name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Frontend quality gate

UI changes: `cd frontend && npm run lint` must be clean (enforces jsx-no-undef/no-undef —
esbuild does not catch undefined components, which has crashed the UI twice) and
`npm run build` must succeed before commit. See `frontend/eslint.config.mjs`.
