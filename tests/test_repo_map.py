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
"""Repo map: tree + signatures within budget, engine injection."""

from helpers import scripted
from pydantic_ai.messages import ModelResponse, TextPart

from codingdude.repo_map import build_repo_map


def make_project(workdir):
    src = workdir / 'src'
    src.mkdir(exist_ok=True)
    (src / 'engine.py').write_text(
        'class Engine:\n'
        '    def start(self):\n        pass\n'
    )
    (src / 'util.py').write_text(
        'def helper(value):\n    return value\n'
    )


def test_map_includes_tree_and_signatures(workdir):
    make_project(workdir)
    m = build_repo_map(workdir)
    assert 'engine.py' in m
    assert 'class Engine' in m
    assert 'def start' in m
    assert 'def helper' in m


def test_map_counts_exclude_skip_dirs(workdir):
    """Files under the shared skip rule (SKIP_DIRS, .venv* siblings, plain
    venv) never enter the map — neither the count line nor
    their tree entries/signatures (regression net for the pruned-walk rewrite)."""
    make_project(workdir)
    (workdir / 'node_modules').mkdir()
    (workdir / 'node_modules' / 'dep.js').write_text('function bundled() {}')
    (workdir / '.venv').mkdir()
    (workdir / '.venv' / 'vendored.py').write_text('def vendored(): pass')
    (workdir / '.venv-verify').mkdir()
    (workdir / '.venv-verify' / 'shadow.py').write_text('def shadow(): pass')
    (workdir / 'venv').mkdir()
    (workdir / 'venv' / 'vtools.py').write_text('def vtool(): pass')
    m = build_repo_map(workdir)
    assert m.startswith('[repo: 3 source files]')
    assert 'node_modules' not in m
    assert 'bundled' not in m
    assert '.venv' not in m
    assert 'vendored' not in m
    assert '.venv-verify' not in m
    assert 'shadow' not in m
    assert 'vtool' not in m


def test_map_excludes_scratch(workdir):
    """Harness-owned .scratch (probes, restart logs) is not project source —
    it must not enter the walk, the count, or burn the signature budget."""
    make_project(workdir)
    scratch = workdir / '.scratch'
    scratch.mkdir()
    (scratch / 'probe_turn_costs.py').write_text('def probe_cost(): pass')
    (scratch / 'probe.mjs').write_text('export function scratchTool() {}')
    m = build_repo_map(workdir)
    assert m.startswith('[repo: 3 source files]')
    assert '.scratch' not in m
    assert 'probe_cost' not in m
    assert 'scratchTool' not in m


def test_budget_truncates_map(workdir):
    make_project(workdir)
    tiny = build_repo_map(workdir, budget=60)
    assert len(tiny) <= 62
    assert 'truncated' in tiny or tiny


async def test_repo_map_reaches_model_instructions(home, workdir):
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    make_project(workdir)
    engine = Engine(config=load_config(), db=Database.connect(home))

    def instruction_echo(messages, info):
        text = getattr(info, 'instructions', '') or ''
        return ModelResponse(parts=[TextPart(content=text[-6000:])])

    outcome = await engine.run(
        prompt='hi', workdir=workdir, model=scripted(instruction_echo)
    )
    assert 'class Engine' in outcome.output
