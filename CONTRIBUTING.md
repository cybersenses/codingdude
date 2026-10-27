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

Questions and setup help go to the [community Discord](https://discord.gg/UA73mmfb)
(`#help` forum) — support happens in public. Security issues go to
security@cyberflex.io per [SECURITY.md](SECURITY.md), never to issues.

## Development setup

```bash
uv sync
uv run pytest -q          # tests
uv run ruff check src tests
uv run mypy
```

Frontend (`frontend/`): `npm run lint`, `npm test` (vitest), and
`npm run build` must all be clean — CI enforces all three.

## Ground rules

1. **Tests with behavior changes.** New or changed behavior ships with
   tests at the existing seams (`tests/` mirrors module layout).
2. **Gates green.** `pytest`, `ruff`, and `mypy` must pass; frontend
   changes must lint, pass vitest, and build.
3. **Match the codebase style.** Guard clauses, early returns, flat
   logic; see `CONTEXT.md` for domain vocabulary.
4. **Commits**: imperative subject line, ticket number when applicable
   (`R51 #214: ...`).
5. **No secrets.** Never commit API keys; config lives in
   `~/.codingdude/config.toml` or environment variables.
6. **Copyright headers** (`Copyright (C) 2025 Cyberflex`) are added by
   maintainers when new files land.

## Pull requests

`main` is protected: every change lands as a squash-merged PR,
maintainers included. One logical change per PR, described in terms of
the ticket/issue it closes.

1. Branch from `main` — `feat/<slug>`, `fix/<slug>`, or `docs/<slug>`.
2. Open the PR with a filled-in template; the PR title becomes the
   squash commit subject, so keep it imperative and specific.
3. **Evidence in the body**: the gates you actually ran, with counts
   (pytest N passed, vitest N/N, lint clean, build ok). "Should pass"
   is not evidence.
4. Wait for CI: the `test` and `frontend` jobs are required checks;
   `bench` is advisory.
5. Address review. Maintainers aim to respond within a week.

After merge: the PR is squash-merged and its branch deleted. A
maintainer adds the CHANGELOG entry under `## Unreleased` and handles
the release train (semver, tags — see `docs/GITHUB-STRATEGY.md`).

