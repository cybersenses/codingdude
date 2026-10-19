# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Run events: structured observations surfaced to frontends (and tests)."""

from dataclasses import dataclass

# Event types that end a run's event stream (shared by worker, server, tests).
TERMINAL_EVENTS = ('RUN_FINISHED', 'RUN_ERROR', 'RUN_CANCELLED')


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
