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
"""Single seam for parsing untrusted/user Python source.

User workdirs contain third-party files with pre-3.12 idioms (e.g. non-raw
"\\s" regex strings) that emit SyntaxWarning on every parse. Those warnings
are noise from our tooling, not actionable here — suppress them. Parse
failures still raise SyntaxError to callers.
"""

import ast
import warnings


def parse_python(source: str) -> ast.Module:
    """Parse Python source with SyntaxWarning suppressed."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', SyntaxWarning)
        return ast.parse(source)
