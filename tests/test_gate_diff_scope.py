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
"""Gate diff-scope: pre-existing findings warn, findings on changed lines block."""

from codingdude.tools import changed_line_numbers, partition_findings


def test_changed_lines_single_edit():
    before = 'a = 1\nb = 2\nc = 3\n'
    after = 'a = 1\nb = 99\nc = 3\n'
    assert changed_line_numbers(before, after) == {2}


def test_changed_lines_identical_content_is_empty():
    text = 'a = 1\nb = 2\n'
    assert changed_line_numbers(text, text) == set()


def test_changed_lines_new_file_all_lines_changed():
    after = 'x = 1\ny = 2\n'
    assert changed_line_numbers('', after) == {1, 2}


def test_partition_splits_on_changed_lines():
    findings = [
        {'id': 'B1', 'line': 2, 'severity': 'Medium', 'message': 'new'},
        {'id': 'B2', 'line': 50, 'severity': 'Low', 'message': 'pre-existing'},
    ]
    blocking, preexisting = partition_findings(findings, {2})
    assert [f['id'] for f in blocking] == ['B1']
    assert [f['id'] for f in preexisting] == ['B2']


def test_partition_line_zero_is_always_blocking():
    findings = [{'id': 'S1', 'line': 0, 'severity': 'High', 'message': 'secret'}]
    blocking, preexisting = partition_findings(findings, set())
    assert blocking == findings and preexisting == []
