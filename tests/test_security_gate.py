"""Security gate (R47 #155): Bandit + secrets scan on edited file content."""

from codingdude.security import format_findings, scan_source

CLEAN_PY = 'def add(a, b):\n    return a + b\n'

VULN_PY = (
    'import subprocess\n'
    'def run(cmd):\n'
    "    return subprocess.Popen(cmd, shell=True)\n"
)

SECRET_PY = (
    'API_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
    'def f():\n    return API_KEY\n'
)


def test_clean_python_source_has_no_findings(tmp_path):
    target = tmp_path / 'clean.py'
    target.write_text(CLEAN_PY, encoding='utf-8')
    assert scan_source('clean.py', CLEAN_PY, '.py', tmp_path) == []


def test_shell_true_python_is_flagged(tmp_path):
    target = tmp_path / 'vuln.py'
    target.write_text(VULN_PY, encoding='utf-8')
    findings = scan_source('vuln.py', VULN_PY, '.py', tmp_path)
    assert findings, 'subprocess with shell=True must be flagged'
    assert any('shell=True' in f['message'] or 'B602' in f['id'] for f in findings)


def test_hardcoded_aws_key_is_flagged_in_any_file(tmp_path):
    target = tmp_path / 'config.txt'
    target.write_text(SECRET_PY, encoding='utf-8')
    findings = scan_source('config.txt', SECRET_PY, '.txt', tmp_path)
    assert findings, 'hardcoded AWS key must be flagged'
    assert any(f['id'] == 'SECRET' for f in findings)


def test_private_key_block_is_flagged(tmp_path):
    src = '-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----\n'
    findings = scan_source('id_rsa', src, '', tmp_path)
    assert any(f['id'] == 'SECRET' for f in findings)


def test_non_python_files_skip_bandit_but_not_secrets(tmp_path):
    target = tmp_path / 'notes.txt'
    target.write_text('just text\n', encoding='utf-8')
    # bandit never runs (no crash), secrets scan still applies.
    assert scan_source('notes.txt', 'just text\n', '.txt', tmp_path) == []


def test_format_findings_renders_actionable_message(tmp_path):
    findings = [
        {'id': 'B602', 'line': 3, 'severity': 'HIGH', 'message': 'shell=True'},
        {'id': 'SECRET', 'line': 1, 'severity': 'HIGH', 'message': 'AWS key'},
    ]
    msg = format_findings('vuln.py', findings)
    assert 'vuln.py' in msg
    assert 'B602' in msg and 'SECRET' in msg
    assert ':3' in msg and ':1' in msg
    assert 'rejecting the write' in msg


# --- wiring: the gate blocks the edit tools (integration) ---

def _tool(toolset, name):
    return toolset.tools[name].function


def test_write_file_blocks_vulnerable_python(tmp_path):
    import pydantic_ai

    write = _tool(__import__('codingdude.tools', fromlist=['x']).build_toolset(tmp_path), 'write_file')
    try:
        write('bad.py', VULN_PY)
    except pydantic_ai.ModelRetry as exc:
        assert 'security gate' in str(exc)
    else:
        raise AssertionError('vulnerable write was not blocked')
    assert not (tmp_path / 'bad.py').exists(), 'blocked content must not hit disk'


def test_write_file_blocks_hardcoded_secret(tmp_path):
    import pydantic_ai

    write = _tool(__import__('codingdude.tools', fromlist=['x']).build_toolset(tmp_path), 'write_file')
    try:
        write('conf.toml', SECRET_PY)
    except pydantic_ai.ModelRetry as exc:
        assert 'security gate' in str(exc)
    else:
        raise AssertionError('secret-bearing write was not blocked')


def test_write_file_allows_clean_code(tmp_path):
    build_toolset = __import__('codingdude.tools', fromlist=['x']).build_toolset
    write = _tool(build_toolset(tmp_path), 'write_file')
    out = write('ok.py', CLEAN_PY)
    assert 'ok.py' in out
    assert (tmp_path / 'ok.py').exists()
