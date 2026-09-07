"""CLI: version reporting without touching the filesystem."""

import pytest

from codingdude import __version__, cli


def test_version_prints_and_creates_nothing(home, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(['--version'])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out == f'codingdude {__version__}'
    assert not home.exists()
