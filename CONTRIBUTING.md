# Contributing to CodingDude

CodingDude is open source under [AGPL-3.0-or-later](LICENSE) —
contributions are welcome. Before your first pull request, please sign
the [CLA](CLA.md).

## Ways to contribute

- **Bugs**: open an issue with reproduction steps and environment details.
- **Features**: open an issue first describing the use case before
  writing code.
- **Skills / prompts**: improvements to `skills/` and personas are as
  valuable as code changes.
- **Docs**: README, `docs/adr/`, and CONTEXT.md fixes always welcome.

## Development setup

```bash
uv sync
uv run pytest -q          # tests
uv run ruff check src tests
uv run mypy
```

Frontend (`frontend/`): `npm run build` and `npm test` (vitest).

## Ground rules

1. **Tests with behavior changes.** New or changed behavior ships with
   tests at the existing seams (`tests/` mirrors module layout).
2. **Gates green.** `pytest`, `ruff`, and `mypy` must pass; frontend
   changes must build and pass vitest.
3. **Match the codebase style.** Guard clauses, early returns, flat
   logic; see `CONTEXT.md` for domain vocabulary.
4. **Commits**: imperative subject line, ticket number when applicable
   (`R51 #214: ...`).
5. **No secrets.** Never commit API keys; config lives in
   `~/.codingdude/config.toml` or environment variables.
6. **Copyright headers** (`Copyright (C) 2025 Cyberflex`) are added by
   maintainers when new files land.

## Pull requests

- One logical change per PR, described in terms of the ticket/issue it
  closes.
- Include evidence: test counts and gate output in the PR description.
