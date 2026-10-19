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
"""Headless Run: exit codes distinguish success from failure."""


from helpers import say, scripted

import codingdude.cli as cli


def test_headless_success_exits_zero(engine, workdir, capsys):
    code = cli.run_headless(
        engine, workdir, 'greet me', model=scripted(say('done'))
    )
    out = capsys.readouterr().out
    assert code == 0
    assert 'done' in out


def test_headless_model_failure_exits_nonzero(engine, workdir):
    from pydantic_ai.exceptions import ModelAPIError

    def dead(messages, info):
        raise ModelAPIError(model_name='m', message='boom')

    code = cli.run_headless(engine, workdir, 'greet me', model=scripted(dead))
    assert code != 0
