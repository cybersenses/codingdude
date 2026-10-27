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
"""Executed kickoff prompts (R71 #263): first-turn orientation blocks.

Mode selection (greenfield vs existing), project override via
.codingdude.toml [kickoff], and the engine seam that rides the kickoff on a
session's first user prompt only.
"""
from __future__ import annotations

from pathlib import Path

from codingdude.kickoff import (
    compose_first_prompt,
    kickoff_block,
    kickoff_mode,
    split_kickoff,
)


def _write(path: Path, text: str = '') -> None:
    path.write_text(text, encoding='utf-8')


# ---- mode selection ----------------------------------------------------------

def test_empty_dir_is_greenfield(tmp_path):
    assert kickoff_mode(tmp_path) == 'new'


def test_scaffold_only_dir_is_still_greenfield(tmp_path):
    """ensure_project_scaffold runs before the kickoff is computed, so a
    fresh workdir already holds ROADMAP/CONTEXT/HANDOFF/reference — those
    must not flip the mode to 'existing'."""
    _write(tmp_path / 'ROADMAP.md')
    _write(tmp_path / 'CONTEXT.md')
    _write(tmp_path / 'HANDOFF.md')
    (tmp_path / 'reference').mkdir()
    _write(tmp_path / '.codingdude.toml', '[kickoff]\n')
    assert kickoff_mode(tmp_path) == 'new'


def test_git_repo_is_existing(tmp_path):
    (tmp_path / '.git').mkdir()
    assert kickoff_mode(tmp_path) == 'existing'


def test_marker_file_is_existing(tmp_path):
    _write(tmp_path / 'pyproject.toml', '[project]\n')
    assert kickoff_mode(tmp_path) == 'existing'


def test_root_source_file_is_existing(tmp_path):
    _write(tmp_path / 'app.py', 'x = 1\n')
    assert kickoff_mode(tmp_path) == 'existing'


def test_source_within_two_levels_is_existing(tmp_path):
    (tmp_path / 'src').mkdir()
    _write(tmp_path / 'src' / 'app.py', 'x = 1\n')
    assert kickoff_mode(tmp_path) == 'existing'


# ---- text resolution ---------------------------------------------------------

def test_bundled_existing_block(tmp_path):
    (tmp_path / '.git').mkdir()
    mode, text = kickoff_block(tmp_path)
    assert mode == 'existing'
    assert '## Kickoff (existing codebase)' in text


def test_bundled_new_block(tmp_path):
    mode, text = kickoff_block(tmp_path)
    assert mode == 'new'
    assert '## Kickoff (new project)' in text


def test_project_override_wins(tmp_path):
    (tmp_path / '.git').mkdir()
    _write(
        tmp_path / '.codingdude.toml',
        '[kickoff]\nexisting = "CUSTOM PIPELINE RULES"\n',
    )
    mode, text = kickoff_block(tmp_path)
    assert mode == 'existing'
    assert 'CUSTOM PIPELINE RULES' in text
    assert '## Kickoff (existing codebase)' not in text


def test_override_is_stripped_at_the_boundary(tmp_path):
    """Review fix (9c9e1d2): an override is free-form text, so it must carry
    the kickoff header — split_kickoff (UI route, eval export) strips only
    headered text, and an unheadered block would ride every refresh and
    stack on replay."""
    (tmp_path / '.git').mkdir()
    _write(
        tmp_path / '.codingdude.toml',
        '[kickoff]\nexisting = "CUSTOM PIPELINE RULES"\n',
    )
    _mode, text = kickoff_block(tmp_path)
    assert text.startswith('## Kickoff (')
    composed = compose_first_prompt('do the thing', text)
    assert split_kickoff(composed) == 'do the thing'


def test_override_ignores_non_string_and_falls_back(tmp_path):
    (tmp_path / '.git').mkdir()
    _write(tmp_path / '.codingdude.toml', '[kickoff]\nexisting = 5\n')
    mode, text = kickoff_block(tmp_path)
    assert mode == 'existing'
    assert '## Kickoff (existing codebase)' in text


# ---- composition -------------------------------------------------------------

def test_compose_first_prompt():
    out = compose_first_prompt('do the thing', 'KICKOFF TEXT')
    assert out == 'KICKOFF TEXT\n\n---\n\ndo the thing'


def test_split_kickoff_strips_composed():
    assert split_kickoff('## Kickoff (new project)\nbody\n\n---\n\nreal ask') == 'real ask'


def test_split_kickoff_passthrough_plain():
    assert split_kickoff('just a question') == 'just a question'


def test_split_kickoff_passthrough_separator_without_header():
    """A user message that merely contains '---' is never touched."""
    assert split_kickoff('point A\n\n---\n\npoint B') == 'point A\n\n---\n\npoint B'


# ---- engine seam -------------------------------------------------------------

def _last_user_text(messages) -> str:
    """The current request's prompt: the last user part (history replays
    earlier turns first, including turn one's kickoff — that's expected)."""
    texts = []
    for m in messages:
        for p in getattr(m, 'parts', []):
            if getattr(p, 'part_kind', '') == 'user-prompt':
                content = p.content
                texts.append(content if isinstance(content, str) else str(content))
    return texts[-1] if texts else ''


async def test_first_turn_rides_kickoff(home, workdir):
    """Session turn 1: the kickoff precedes the user's prompt and the trace
    records a KICKOFF event with the mode."""
    from helpers import scripted

    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    captured: list[str] = []
    events: list[dict] = []

    def model_fn(messages, info):
        captured.append(_last_user_text(messages))
        from pydantic_ai.messages import ModelResponse, TextPart

        return ModelResponse(parts=[TextPart(content='ok')])

    engine = Engine(config=load_config(), db=Database.connect(home))
    outcome = await engine.run(
        prompt='fix the login bug', workdir=workdir,
        model=scripted(model_fn), approvals=ApprovalPolicy(),
        emit=events.append,
    )
    assert outcome.output == 'ok'
    assert 'fix the login bug' in captured[0]
    assert '## Kickoff (existing codebase)' in captured[0]
    assert captured[0].index('## Kickoff (existing codebase)') < captured[0].index('fix the login bug')
    kickoff_events = [e for e in events if e.get('type') == 'KICKOFF']
    assert kickoff_events and kickoff_events[0]['mode'] == 'existing'


async def test_second_turn_has_no_kickoff(home, workdir):
    """Session turn 2+: history exists, so the user's prompt rides alone."""
    from helpers import scripted

    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    captured: list[str] = []
    events: list[dict] = []

    def model_fn(messages, info):
        captured.append(_last_user_text(messages))
        from pydantic_ai.messages import ModelResponse, TextPart

        return ModelResponse(parts=[TextPart(content='ok')])

    engine = Engine(config=load_config(), db=Database.connect(home))
    first = await engine.run(
        prompt='turn one', workdir=workdir,
        model=scripted(model_fn), approvals=ApprovalPolicy(),
        emit=events.append,
    )
    second = await engine.run(
        prompt='turn two', session_id=first.session_id, workdir=workdir,
        model=scripted(model_fn), approvals=ApprovalPolicy(),
        emit=events.append,
    )
    assert second.output == 'ok'
    assert 'turn two' in captured[-1]
    assert '## Kickoff' not in captured[-1]
    assert [e for e in events if e.get('type') == 'KICKOFF']  # turn one only fired once
