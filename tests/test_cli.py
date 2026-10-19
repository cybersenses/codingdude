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
"""CLI: version reporting without touching the filesystem."""

import asyncio
from pathlib import Path

import pytest

from codingdude import __version__, cli
from codingdude.config import load_config
from codingdude.db import Database


def test_version_prints_and_creates_nothing(home, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(['--version'])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out == f'codingdude {__version__}'
    assert not home.exists()


def test_eval_record_then_replay(tmp_path, home, capsys):
    """R7 thickener: record a scenario from a real session's persisted
    messages, then replay it via the CLI — exit 0 when checks pass."""
    import sys as _sys

    from codingdude.engine import Engine
    from codingdude.evals import load_scenario

    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in _sys.path:
        _sys.path.insert(0, str(tests_dir))
    from helpers import scripted  # type: ignore[import-not-found]

    db = Database.connect(home)
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    engine = Engine(config=load_config(), db=db)

    def model(messages, info):
        from pydantic_ai.messages import ModelResponse, TextPart

        return ModelResponse(parts=[TextPart(content='ZEBRA-RULE echoed')])

    outcome = asyncio.run(engine.run(
        prompt='repeat ZEBRA-RULE', workdir=workdir,
        model=scripted(model), emit=lambda event: None,
    ))
    assert outcome.status == 'complete', outcome

    scenarios = tmp_path / 'scenarios'
    code = cli.main([
        'eval', '--record', outcome.session_id,
        '--name', 'recorded-echo', '--out', str(scenarios / 'recorded-echo.json'),
        '--check', 'user_prompt_first', '--check', 'directive_echo',
    ])
    assert code == 0
    scenario = load_scenario(scenarios / 'recorded-echo.json')
    assert scenario['prompt'] == 'repeat ZEBRA-RULE'
    assert scenario['checks'] == ['user_prompt_first', 'directive_echo']
    assert 'recorded' in capsys.readouterr().out

    # Replay the recorded scenario back through the CLI runner.
    code = cli.main(['eval', '--scenarios', str(scenarios), '--workdir', str(workdir)])
    assert code == 0
    assert '1 scenario passed' in capsys.readouterr().out


def test_eval_replay_fails_on_broken_check(tmp_path, home, capsys):
    """A failing check must surface as exit code 1 with a readable failure."""
    from codingdude.evals import write_scenario

    scenarios = tmp_path / 'scenarios'
    write_scenario(
        {'name': 'broken', 'prompt': 'hi', 'responses': [], 'checks': ['tool_call_executed']},
        scenarios / 'broken.json',
    )
    code = cli.main([
        'eval', '--scenarios', str(scenarios), '--workdir', str(tmp_path),
    ])
    assert code == 1
    assert "tool_call_executed" in capsys.readouterr().err
