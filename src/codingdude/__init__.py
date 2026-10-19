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
"""CodingDude — a personal coding agent built with pydantic-ai."""

from importlib.metadata import PackageNotFoundError, version


def _package_version() -> str:
    """Version from installed package metadata (pyproject.toml), '0.0.0' if unreadable."""
    try:
        return version("codingdude")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _package_version()
