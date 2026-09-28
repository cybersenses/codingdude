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
