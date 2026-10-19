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
"""CodingDude exception taxonomy. Everything user-visible derives from the base."""


class CodingDudeError(Exception):
    """Base for all CodingDude-specific errors."""


class BudgetExceeded(CodingDudeError):
    """A Session crossed its Budget Cap; the run is hard-stopped."""

    def __init__(self, spent_usd: float, cap_usd: float):
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
        super().__init__(
            f'Budget cap exceeded: ${spent_usd:.2f} spent (cap ${cap_usd:.2f})'
        )


class ConfigError(CodingDudeError):
    """Configuration is invalid or contradictory."""


class GateRequired(CodingDudeError):
    """An action needs Approval; the run pauses/aborts per ADR-0003."""

    def __init__(self, command: str):
        self.command = command
        super().__init__(f'gate required for: {command}')
