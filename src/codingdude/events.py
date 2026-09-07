"""Run events: structured observations surfaced to frontends (and tests)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EditChange:
    """A file changed by the agent; carries before/after for diff rendering."""

    kind: str  # 'edit'
    path: str
    before: str
    after: str


@dataclass(frozen=True)
class CompactionCheckpoint:
    """Old history was compacted; visible marker in the timeline."""

    kind: str  # 'compaction'
    summarized_messages: int
    summary: str
