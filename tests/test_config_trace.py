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
"""R79 #291: [trace] config section — delta mode defaults, round trip, fail-fast.

Sibling of test_config.py (R66 lesson: that file carries mixed line endings,
so new tests land in their own file instead of forcing a whole-file rewrite).
"""

import pytest

from codingdude.config import load_config


def test_trace_section_defaults_to_compact(home):
    """No [trace] section means compact delta coalescing (R79 default)."""
    config = load_config()
    assert config.trace.deltas == 'compact'
    assert config.trace.flush_bytes == 4096
    assert config.trace.flush_ms == 250.0


def test_trace_section_round_trip(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.toml').write_text(
        '[trace]\ndeltas = "full"\nflush_bytes = 8192\nflush_ms = 100.0\n',
        encoding='utf-8',
    )
    config = load_config()
    assert config.trace.deltas == 'full'
    assert config.trace.flush_bytes == 8192
    assert config.trace.flush_ms == 100.0


def test_trace_section_rejects_unknown_mode(home):
    """An unknown deltas value fails fast at the config boundary."""
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.toml').write_text('[trace]\ndeltas = "zip"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='must be "compact" or "full"'):
        load_config()
