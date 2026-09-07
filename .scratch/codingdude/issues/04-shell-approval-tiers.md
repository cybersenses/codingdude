# 04: Shell tool + Approval tiers

**What to build:** CodingDude can run commands under the agreed tier table. The shell tool executes through Git Bash (per-project configurable), reads/searches/in-Workdir edits stay auto-approved, shell commands gate behind Approval with session-scoped Pattern Approval, and the always-gated tier (remote mutations, outside-Workdir access, deletions) can never be unlocked by a pattern. In Headless Runs a gate means abort-with-report per ADR-0003, with distinct exit codes; `--yolo` explicitly disables the gates.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** resolved

- [x] A scripted run runs an approved shell command and reads its output (exit code, stdout/stderr, truncated)
- [x] A gated shell action in a headless run aborts with a report of the exact command; exit code differs from success and from failure (2 vs 0/1)
- [x] Injecting an Approval plus Pattern Approval at the engine seam lets all matching commands run for the rest of the Session
- [x] An always-gated action (e.g. `git push`) is not unlocked by any pattern approval
- [x] `--yolo` executes gated actions without pausing
- [x] Shell is Git Bash by default; a per-project config selects PowerShell

## Comments

2026-09-07: Commit e491217. ApprovalPolicy encodes the tier table (auto-shell regex / pattern set / always-gated regex); patterns are the command's leading token and can never unlock the always-gated tier — only yolo does. The shell tool is only attached to the agent when an ApprovalPolicy is provided, so read-only contexts don't expose it. Per-project `.codingdude.toml` (shell = "powershell") overrides the default.
