# 01: Foundations & rename

**What to build:** The prefactor that makes everything else easy. CodingDude exists as a project: the placeholder prototype is deleted, the package/CLI is named `codingdude`, the repo is git-initialized, and the user config directory holds the model lineup (main `deepseek-v4-pro`, Subagents `deepseek-v4-flash`, failover `glm-5.3` via FallbackModel) and shell setting (Git Bash default). The SQLite schema for sessions, messages, approvals, Memory, and usage exists, and the FunctionModel test harness with temp-Workdir fixtures proves itself green by running one trivial scripted run end-to-end and finding it persisted.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `codingdude` installs and runs as the CLI name; the old prototype code is gone
- [ ] Repo is a git repository with an initial commit
- [ ] First run creates the config directory and SQLite database without manual steps
- [ ] Engine-seam harness (FunctionModel + temp Workdir fixtures) runs a scripted turn and the messages appear in the database
- [ ] A scripted run against a dead primary model transparently failsover to the fallback model
