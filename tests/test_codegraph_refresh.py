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
