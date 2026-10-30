# GitHub Strategy

How this repository is run: branches, CI, issues, reviews, releases, and
what flips when the repo goes public. Adopted under R73 (#267); the
public-facing contract lives in `CONTRIBUTING.md`, the community intake
in `docs/COMMUNITY.md`.

## Decisions

Recorded 2026-10-27 (see `docs/adr/0005-pr-based-github-workflow.md`):

1. **Private now, public later.** The strategy is written for strangers;
   the public-only parts are explicitly gated (see *Going public*).
2. **PRs for everyone** — maintainers and agents included. `main` is
   protected: no direct pushes, no force-pushes.
3. **Formal releases.** Semver; `CHANGELOG.md` gains an entry on every
   merge; every release is tagged.

## Branch model

- `main` is protected. Every change lands as a **squash-merged PR**, so
  the PR title becomes the commit subject — existing commit conventions
  (imperative subject, `R73 #267` suffixes) apply unchanged.
- Branch naming: humans use `feat/<slug>`, `fix/<slug>`, `docs/<slug>`;
  agents use `codingdude/<name>` (the worktree-tooling convention).
- One logical change per PR (existing CONTRIBUTING rule).

## CI policy

| Job        | Contents                              | Status                    |
| ---------- | ------------------------------------- | ------------------------- |
| `test`     | ruff, mypy, pytest                    | **required**              |
| `frontend` | `npm ci`, eslint, vitest, vite build  | **required**              |
| `bench`    | `bench.py` benchmark                  | advisory — never blocks   |

Windows runners throughout, matching the dev environment. Bench is
advisory on purpose: benchmark noise must never block a merge; measured
performance work goes through `compare_bench` evidence instead.

## Workflow for maintainers and agents

Consent vocabulary (agent-facing; the standing rule *never push without
consent* still holds):

- **"push"** → create the branch, push it, open the PR. CI runs.
  Nothing lands yet.
- **"merge"** → squash-merge the PR and delete the branch.
- Feature PRs get a code-review pass (the `code-review` skill over the
  PR diff) **before** merge — the old post-push review becomes
  pre-merge review, which is the same review moved earlier, not a new
  one.
- Urgent fixes take the same path; speed comes from reviewing them
  first, never from bypassing protection.

## Issues: two populations, one bridge

- **Our work**: the local planning store is the source of truth
  (roadmap items `R#`, tickets `#N`, `code-design.md` entries).
  `gh_mirror` (R53) mirrors ticket/roadmap creates and done-transitions
  **one-way** to GitHub issues with the `done` label. GitHub is the
  public face, never the source.
- **External reports**: GitHub issues (via templates) are triaged with
  the five-role vocabulary already canonical in
  `docs/agents/triage-labels.md`: `needs-triage`, `needs-info`,
  `ready-for-agent`, `ready-for-human`, `wontfix` — plus the default
  `bug` / `enhancement` / `documentation` kinds.
- **Promotion path**: an accepted external issue becomes a local ticket
  (with the `Audience:` first line, per AGENTS.md). `gh_mirror` then
  auto-creates a *mirror* issue for that ticket; close the mirror
  immediately as `duplicate` with a cross-link to the promoted issue.
  This manual step is deliberate — no two-way mirror until volume
  justifies building one.
- **Discord** (`#bugs` / `#ideas`, per `docs/COMMUNITY.md`) funnels
  here: a maintainer opens the GitHub issue from a confirmed thread.

## Reviews

- Every PR carries evidence in the body (template-enforced): gates
  actually run with counts — pytest N passed, vitest N/N, lint clean,
  build ok. "Should pass" is not evidence.
- `claim_check` runs before every commit (R71 gate order).
- Single-maintainer reality: the one approval is nominally
  self-approval; the pre-merge code-review pass is the real control.
  When collaborators arrive, this becomes a true second pair of eyes.

## Reviewer runbook (external PRs)

What happens when a stranger opens a PR, in order. A PR is an issue
with attached code: same triage roles, same states, plus the
AI-generated-comment disclaimer on everything we post.

1. **CI before review.** First-time contributors' workflow runs need a
   manual "Approve and run workflows" click — deliberate GitHub
   friction; click it. Never review a red PR. If required checks fail
   on our side (flaky gate, stale docs), we fix or explain in a
   comment; otherwise the ball is the contributor's.
2. **Verify the claim.** Check out the branch and run the gates cited
   in the body. Report confirmed (with code path), failed, or
   insufficient detail — the last is a strong `needs-info` signal.
3. **Scope gate.** One logical change. Feature PRs without a promoting
   issue go back to issue-first (comment, don't merge). Mass
   reformatting and drive-by refactors close without ceremony;
   rejected enhancement requests are recorded in `.out-of-scope/`.
4. **Code review.** The `code-review` skill over the diff: correctness
   (verified, not claimed), standards (CONTRIBUTING ground rules +
   CONTEXT.md vocabulary), tests at real seams. Diffs touching auth,
   filesystem paths, subprocess spawning, or config handling get
   mandatory scrutiny; vendored third-party code gets a license look
   before anything else.
5. **Decide.** Squash-merge (title becomes the subject) or close with
   a plain-language reason. Low quality closes without ceremony —
   slow merges are fine, fake contributor counts are not.
6. **Post-merge ceremony is ours.** Contributors meet CONTRIBUTING's
   ground rules; maintainers apply the rest: local ticket + roadmap
   entry, `code-design.md` entry where the design moved, CHANGELOG
   entry, release train.

Standing decisions (2026-10-27, post-public):

- **CLA is checked by hand** during review; a CLA bot waits for volume
  (see *Going public* step 2).
- **No required-review rule** on branch protection: external PRs
  cannot merge regardless (maintainer-only merge rights); requiring a
  review count would only add friction to maintainer PRs.
- **The local tracker records only our work**: an external PR gets a
  local ticket only if it merges.

## Releases

- Semver. The version lives in **two** places and moves together:
  `pyproject.toml` and `frontend/package.json`.
- `CHANGELOG.md` is Keep-a-Changelog style; every merge updates
  `## Unreleased` (the PR author adds their entry).
- Release runbook:
  1. Bump both versions.
  2. Fold `## Unreleased` into `## X.Y.Z — <date>`.
  3. Land the release commit (`chore(release): vX.Y.Z`) via PR.
  4. Tag `vX.Y.Z` on `main` after the merge; push the tag.
  5. GitHub release with the CHANGELOG section as notes.
- Tags only ever point at `main`.

## Security intake

`SECURITY.md` stands: vulnerabilities go to security@cyberflex.io,
never to public issues. Fixes take the same PR flow with expedited
review; disclosure waits for the fix release.

## Going public (gated checklist)

Written for strangers on day one, so going public is small:

1. Flip visibility. Nothing above changes.
2. CLA: the PR template already asks; add CLA-assistant (or similar)
   when volume arrives — not before.
3. Issue templates, triage labels, and community intake already live.
4. Before announcing: verify a fresh-clone setup (uv sync → gates →
   run) on a clean machine.

## Activation sequence (this repo, in order)

1. This change lands: templates, CI jobs, labels.
2. The first PR runs `test` and `frontend` — this names the checks.
3. Enable branch protection on `main`: required status checks `test`
   and `frontend`, PRs required, squash only. (Admin API, maintainer
   runs it — it cannot be enabled before step 2 names the checks.)
4. From then on: everything via PR, including the agent.

## Known limitations (deliberate)

- `gh_mirror` is one-way; promotion duplication is handled by the
  manual close-as-duplicate step above.
- Bench being advisory means performance regressions are caught by
  bench runs and profiling discipline, not by the merge gate.
- Until branch protection is enabled (activation step 3), direct
  pushes to `main` remain technically possible; the convention applies
  from the moment this doc lands.
