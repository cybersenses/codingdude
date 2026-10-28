# PRs for everyone: protected main and a formal release train

Once code flows in from more than one place — a second maintainer, an
AFK agent, external contributors — direct pushes to `main` stop being a
convenience and become the thing that makes review unequally applied.
CodingDude's answer is to run the repo the way it will be run when
public: `main` is protected, every change (maintainers and agents
included) lands as a squash-merged PR whose required checks are the
gates we already run locally (ruff, mypy, pytest, and the frontend
lint/vitest/build that CI previously did not run at all), and releases
become a formal semver train with a CHANGELOG entry on every merge. The
trade: shipping takes two consents instead of one ("push" opens the PR,
"merge" lands it), and benchmark noise is deliberately kept advisory so
the required checks stay deterministic. Designed private-first so going
public later is a visibility flip plus a CLA bot, not a process change.

## Considered Options

- **Trunk-based, direct push for trusted accounts, PRs for externals**
  — rejected: two processes for one repo; the agent's pushes would be
  exactly the unreviewed writes the post-push-review ritual kept
  catching.
- **Direct push forever, review after the fact** — rejected: it was
  already the de-facto process and its cost was visible (post-push
  reviews on R69/R71/R72 repeatedly moved fixes back onto main).
- **PRs for everyone, protection on, formal releases** — adopted.
