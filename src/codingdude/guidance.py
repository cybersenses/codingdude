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
#
"""Guidance blocks appended to the system instructions (user-feedback
round 1): real platform facts and the behavioral contract the user asked
to be enforced at instruction level.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path


def platform_block(workdir: Path) -> str:
    """The machine the agent is actually running on — prevents the classic
    'this is not a Windows machine' mistake on a Windows host."""
    return (
        '\n\n## Platform (facts, verified — never assume otherwise)\n'
        f'- OS: {platform.system()} {platform.release()} ({sys.platform})\n'
        f'- Python: {sys.version.split()[0]}\n'
        f'- Project directory: {workdir}\n'
        'Path handling must match this platform (drive letters / separators).'
    )


def contract_block() -> str:
    """Behavioral contract distilled from user feedback. Instruction-level
    by design — no mechanical gate."""
    return (
        '\n\n## Working contract\n'
        '- If the request asks you to evaluate, assess, review, or give an '
        'opinion: report findings only. Do NOT start fixing anything until '
        'asked.\n'
        '- If you ask the user a question (ask_user or a choice card): stop '
        'and wait for the answer. Never answer your own question and plow '
        'ahead.\n'
        '- Plan before non-trivial work and state the plan first; never '
        'bypass planning.\n'
        '- On a missing dependency (runtime, package, CLI): check whether it '
        'is available and offer to install it — do not just report it '
        'missing.\n'
        '- Be terse. No information overload.'
    )
