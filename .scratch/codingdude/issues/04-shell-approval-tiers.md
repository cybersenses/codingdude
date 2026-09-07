# 04: Shell tool + Approval tiers

**What to build:** CodingDude can run commands under the agreed tier table. The shell tool executes through Git Bash (per-project configurable), reads/searches/in-Workdir edits stay auto-approved, shell commands gate behind Approval with session-scoped Pattern Approval, and the always-gated tier (remote mutations, outside-Workdir access, deletions) can never be unlocked by a pattern. In Headless Runs a gate means abort-with-report per ADR-0003, with distinct exit codes; `--yolo` explicitly disables the gates.

**Blocked by:** 02 (Read-only tracer bullet)

**Status:** ready-for-agent

- [ ] A scripted run runs an approved shell command and reads its output (exit code, stdout/stderr, truncated)
- [ ] A gated shell action in a headless run aborts with a report of the exact command; exit code differs from success and from failure
- [ ] Injecting an Approval plus Pattern Approval at the engine seam lets all matching commands run for the rest of the Session
- [ ] An always-gated action (e.g. `git push`) is not unlocked by any pattern approval
- [ ] `--yolo` executes gated actions without pausing
- [ ] Shell is Git Bash by default; a per-project config selects PowerShell
