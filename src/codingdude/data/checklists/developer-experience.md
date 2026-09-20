# Developer experience (CLI & tooling) checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-developer-tooling-engineer.md
Use when: building CLIs, scripts, or internal developer tools.

## Checklist
- [ ] Every error states what happened, why, and the exact fix ("Config not found at ./app.toml — run `mytool init`"). Stack traces only behind `--verbose`. A non-actionable error is a defect.
- [ ] Dual output: TTY detection → rich output for humans (colors/tables/spinners); piped/redirected → plain, stable, parseable output (`--json`, no ANSI). A tool that dumps color codes into a pipe is broken.
- [ ] Exit codes are an API: 0 success, distinct nonzero classes per failure type. Scripts and CI depend on them.
- [ ] Flag consistency: `-v` means verbose everywhere, never sometimes-version. Verb-noun command hierarchy users can guess.
- [ ] Startup < 100ms for hot-path tools: lazy-load commands, cache credentials, no network or eager config parsing on the hot path; startup-time assertion in CI.
- [ ] `--help` is the primary docs: one-line summary, flag descriptions, real usage examples at every level; bare invocation shows a useful overview.
- [ ] Safety: destructive actions confirm or require `--force`; `--dry-run` for any state change; sensible defaults cover the common case.
- [ ] Interface is a contract: flags/output/exit codes versioned; breaking changes get deprecation warnings + migration path (someone's cron depends on today's behavior).
- [ ] Config precedence documented: flag > env var > config file > defaults; never log secrets.
- [ ] Distribution: one-line or single-binary install, `--version`, shell completions, respects `NO_COLOR`/`$PAGER`.

## Failure modes
- 900ms startup on a tool run 300×/day — users route around it with aliases, adoption dies.
- Cryptic errors ("Error: 403") generating support tickets a fix-naming message would prevent.
- Renaming a flag without a deprecated alias — silently breaking every downstream script.
- Human-only output: no `--json`, CI can't consume it.

## Rejected
- Internal-platform/IDP program design, plugin architecture essays, TUI-vs-CLI debates.
