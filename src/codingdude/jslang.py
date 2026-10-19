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
"""tree-sitter language selection for JS/TS files (self-review M14).

`.ts` and `.tsx` get the TypeScript grammar (so TS-only syntax — interfaces,
type annotations, generics — parses correctly); everything else gets the
JavaScript grammar. Missing TypeScript grammar degrades to JavaScript rather
than crashing. Delegates to the langs registry (R26).
"""

from tree_sitter import Language

from .langs import spec_for

__all__ = ['language_for']


def language_for(suffix: str) -> Language:
    """The tree-sitter Language for a file suffix ('.ts'/'.tsx' -> TypeScript).

    Falls back to the JavaScript grammar when TypeScript is unavailable or the
    suffix is unregistered."""
    spec = spec_for(suffix)
    if spec is not None:
        return spec.grammar
    js = spec_for('.js')
    if js is None:  # pragma: no cover - JS grammar is a hard dependency
        raise RuntimeError('JavaScript grammar unavailable')
    return js.grammar
