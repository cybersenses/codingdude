"""Run events: structured observations surfaced to frontends (and tests)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EditChange:
    """A file changed by the agent; carries before/after for diff rendering."""

    kind: str  # 'edit'
    path: str
    before: str
    after: str
