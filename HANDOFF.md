# Handoff note - to the next agent on duty

*Updated after commit a3811c9 (pushed). Main == origin/main, tree clean.*

## Current state
- **R33 (Review automation) DONE** - all 3 tickets closed:
  - #66 `0cc5c28`: `prsum.py` - pr_summary tool (commit list, diff stat,
    AST semantic summaries per changed .py file, base..HEAD).
  - #67 `e445c05`: post-push review directive - git_push returns the pushed
    range (pre-push remote head..HEAD) and mandates review -> verified fixes
    -> gates -> commit; never auto-pushes.
  - #68 `404ca97`: review checklist (prompts/review.md) mandates codegraph
    impact analysis on touched symbols + verified-only findings.
- **R34 done earlier this session** (be12533 / afd0241 / a75b458) - Monaco
  file API/editor/diff; live UI check (tree -> edit -> diff -> save) done.
- Gates: 510 passed / 1 skipped, ruff + mypy clean (53 files).

## MUST DO after bounce
- Nothing mandatory. Server serves latest dist (bounced after R34).

## Open roadmap
- R31 (run-end determinism residual) - flicker fix live; scoping pass
  pending. Only open roadmap item.

## Known accepted gaps
- Post-push review loop is directive-driven (tool output guidance), not a
  hard-enforced pipeline - agent discipline may drift.
- Vision pixel gate still has no live end-to-end check.

## Environment notes
- Windows 11, project at G:/pydantic, venv ./.venv/Scripts/.
- Gates: ./.venv/Scripts/python.exe -m pytest -q; ruff check src tests;
  python -m mypy src; frontend: cd frontend && npx vitest run && npm run build.
- WSL git uses Windows GCM for credentials - push works from agent shell
  (git push origin main, ~seconds). Docker CLI: use docker.exe from WSL.
- tools.py and other files are CRLF - preserve; the edit tool keeps
  normalizing some files to LF, restore CRLF pre-commit when diff explodes.
- HANDOFF.md must stay UTF-8 (this file was once cp1252 and blocked edits).

## Process reminders
- TDD red-first at pre-agreed seams; full gates before any done claim.
- Every user message means continue-the-work; user says proceed/afk -> keep
  going without re-asking. Bounce = delivery mechanism, not a new task.
- Keep ROADMAP.md statuses in sync when closing items; ticket tool closes
  record the closing commit.
