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
"""Dependency audit tool: pip-audit / npm audit wrappers."""


async def test_audit_reports_no_manifests(home, tmp_path):
    from codingdude.tools import build_audit_toolset

    empty = tmp_path / 'empty'
    empty.mkdir()
    toolset = build_audit_toolset(empty)
    result = await toolset.tools['dependency_audit'].function()
    assert 'no supported project manifests' in result


async def test_audit_runs_on_project_with_manifest(home, tmp_path):
    from codingdude.tools import build_audit_toolset

    proj = tmp_path / 'proj'
    proj.mkdir()
    (proj / 'requirements.txt').write_text('requests==2.31.0\n')
    toolset = build_audit_toolset(proj)
    result = await toolset.tools['dependency_audit'].function()
    # Either a clean bill or findings — both are valid tool outcomes
    assert 'pip-audit' in result
