"""Project onboarding: first-run discovery of a project's conventions.

An agent taking over a project (from another agent or a fresh checkout) had
no enforced step to discover *where work is tracked* (GitHub Issues,
ROADMAP.md, docs) or the project's gates — so default behaviors won and work
went unlogged. The convention record is a durable workdir Memory entry whose
content starts with MARKER; its presence is the "onboarded" flag, so
detection, injection, and the UI memory panel all read the same source.

Best-effort by design: onboarding nudges, it never blocks a run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from .memory import MemoryStore

MARKER = 'Project conventions:'

_ONBOARDING_BLOCK = """\
## Project onboarding (first session in this workdir)

No convention record exists for this project yet. Before doing the
requested work:
1. Discover the project's conventions: where work is tracked (GitHub
   Issues via `gh`, ROADMAP.md, docs/agents, other), the test/lint/
   type-check commands, and the key process docs (CLAUDE.md, AGENT.md,
   docs/adr).
2. Confirm your findings with the user via ask_user before relying on them.
3. Bank the record durably: call remember() with one entry starting
   exactly 'Project conventions: ' (scope 'workdir') covering tracker,
   commands, and docs.
Until the record exists, open a tracked item in the declared surface
before starting non-trivial work in this project.
"""


def onboarding_needed(store: MemoryStore, workdir: str | Path) -> bool:
    """True while the workdir has no 'Project conventions:' memory entry."""
    wd = str(workdir)
    return not any(
        r['scope'] == 'workdir' and r['workdir'] == wd and MARKER in r['content']
        for r in store.all_entries()
    )


def onboarding_block() -> str:
    """The directive text injected into a not-yet-onboarded run's instructions."""
    return _ONBOARDING_BLOCK


def mark_onboarded(store: MemoryStore, workdir: str | Path, summary: str) -> int:
    """Bank the convention record; forces the MARKER prefix so detection holds."""
    content = summary.strip() or 'recorded'
    if MARKER not in content:
        content = f'{MARKER} {content}'
    return store.add(content, scope='workdir', workdir=str(workdir))
