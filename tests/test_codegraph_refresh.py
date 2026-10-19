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
"""R14: mid-run codegraph index refresh (fix-loop) is best-effort."""

from codingdude.codegraph_boot import refresh_codegraph_index


def test_refresh_runs_even_when_index_exists(tmp_path):
    calls = []
    def runner(argv, cwd, timeout):
        calls.append((argv, cwd, timeout))
        class R:
            returncode = 0
            stdout = 'indexed'
        return R()

    out = refresh_codegraph_index(tmp_path, runner=runner, cli_path='/fake')
    assert out == 'indexed'
    assert calls and 'init' in calls[0][0] and calls[0][2] <= 120


def test_refresh_returns_none_without_cli(tmp_path, monkeypatch):
    import codingdude.codegraph_boot as boot

    monkeypatch.setattr(boot, 'find_codegraph_cli', lambda: None)
    assert boot.refresh_codegraph_index(tmp_path) is None


def test_refresh_swallows_failures(tmp_path):
    def boom(argv, cwd, timeout):
        raise OSError('nope')
    assert refresh_codegraph_index(tmp_path, runner=boom, cli_path='/fake') is None


def test_refresh_nonzero_exit_is_none(tmp_path):
    class R:
        returncode = 1
        stdout = ''
    assert refresh_codegraph_index(
        tmp_path, runner=lambda a, cwd, timeout: R(), cli_path='/fake') is None
