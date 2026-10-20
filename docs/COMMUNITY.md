# Community guidelines

CodingDude's community lives on Discord: **https://discord.gg/UA73mmfb**

This document is the source of truth for how the server is organised and how to
post. It is written to be pasted into Discord directly - see
[Setting up the server](#setting-up-the-server) at the end.

## Principles

The server is small, so it is provisioned small. Over-provisioned servers turn
into ghost towns where every question lands in one chat channel and is never
found again. Channels get added when traffic justifies them, not before.

Two rules follow from that:

- Anything with **state** (a problem being solved, a bug, an idea) goes in a
  **forum channel**, not a chat channel. Forums give filterable tags, one topic
  per thread, and search results that survive.
- Anything answered in a DM is an answer nobody else can find. Support happens
  in public.

## Server layout

| Channel | Type | Purpose |
| --- | --- | --- |
| `#welcome` | text, read-only | Rules, posting guide, links to README / CONTRIBUTING / SECURITY |
| `#announcements` | text, read-only | Releases and breaking changes |
| `#help` | **forum** | Setup and usage questions |
| `#bugs` | **forum** | Confirmed-defect intake |
| `#ideas` | **forum** | Feature, skill, and integration proposals |
| `#general` | text | Everything else; the one chat channel |
| `#dev` | text | Contributors: local dev, tests, ticket conventions |

### Forum tags

| Forum | Tags |
| --- | --- |
| `#help` | `setup` `config` `providers` `approvals` `sandbox` `mcp` `skills` `web-ui` `headless`, plus status `answered` |
| `#bugs` | `needs-info` `confirmed` `fixed` `wontfix` `duplicate` |
| `#ideas` | `feature` `skill` `integration` `docs` |

Settings worth enabling on all three forums:

- **Require tag before posting** - forces classification with no bot.
- **Guidelines field** - paste the per-forum text from this document. It shows
  at post time, which is the highest-compliance placement available.
- **Default sort: recent activity.**
- **Auto-archive: 1 week** - threads stay searchable, the channel stays clean.

Server-wide: enable **rules screening** so members accept the rules once on join.

## Posting guidelines

### Everyone

1. Be civil. Harassment and gatekeeping get you removed - we optimise for people
   asking "obvious" questions.
2. **Search first**, then post. One problem per post.
3. **Never DM for support.** Public posts keep answers searchable.
4. **Never paste secrets** - API keys, tokens, `.env` contents. If you already
   did, rotate the key immediately; deleting the message is not enough.
5. **Security vulnerabilities go to `SECURITY.md`**, never to Discord.
6. **Mark it resolved** - tag `answered`, or reply with the fix. A thread that
   looks unanswered costs someone else an hour.
7. CodingDude is AGPL-3.0. Rebranding it as your own product, or selling
   imposter builds, is not permitted. Report imposters to a maintainer.

### `#help`

Paste this into the forum's guidelines field:

```
What I'm trying to do:
What happens instead:
Environment: CodingDude version (from /health), OS, Python version, model provider
Exact command or UI path:
Logs: ~/.codingdude/logs/ - truncated, secrets removed
What I already tried:
```

- Paste errors as **text, not screenshots**. Screenshots are not searchable and
  cannot be quoted into an issue.
- If it turns into a confirmed defect, a maintainer moves it to `#bugs` or opens
  an issue. That is the intake path into the tracker.

### `#bugs`

- Include repro steps, expected vs actual, and a minimal example. "It doesn't
  work" is not actionable.
- State what you already tried, and whether it is reproducible or one-off.
- Do not file here *and* on GitHub - pick one, a maintainer mirrors it. Local
  first, then GitHub, is the project convention.
- `needs-info` means the thread is waiting on **you**.

### `#ideas`

- **Lead with the problem, not the solution.** "Config edits are too verbose for
  CI" beats "I want YAML configs".
- Say what you are trying to do. At this size, use-cases beat vote counts.
- Ideas are not commitments. Maintainers will not make roadmap promises in chat.

### `#dev`

- Read `CONTRIBUTING.md` before opening a PR.
- Work items are logged locally first (ROADMAP.md item plus ticket), then
  mirrored to a GitHub issue. Keep both in step.

## Mechanics worth the ten minutes

- **A `@maintainer` role**, pinged only when a thread sits unanswered for about
  48 hours. Stops the "anyone here?" pattern.
- **GitHub integration**: release and issue-created webhooks into
  `#announcements` and `#bugs`, so chat and tracker stay in step.
- **Keep `#general` genuinely general.** Every support question answered there
  is a lost answer.

## Setting up the server

Discord has no API for creating channels or tags, so this is a manual pass in
the client. In order:

1. Create the seven channels from the table above. Pick the **Forum** type for
   `#help`, `#bugs`, and `#ideas`.
2. For each forum: set the tags, enable *require tag*, set default sort to
   recent activity, set auto-archive to 1 week, and paste the matching
   guidelines text from this document.
3. Create the `@maintainer` role and restrict posting in `#welcome` and
   `#announcements` to it.
4. Enable rules screening and paste the *Everyone* list above.
5. Post the rules and links in `#welcome`, and pin `CONTRIBUTING.md` in `#dev`.
6. Optionally wire the GitHub webhooks.
