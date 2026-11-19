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
"""R5 tracer: sandboxed prototype environments, tier 1 (worktree+venv).

Seam: the `build_sandbox_toolset` FunctionToolset tools, against a real git
repo — same style as tests/test_worktrees.py. No mocks.
"""

import os
import re
import subprocess
import types
import warnings

import pytest

from codingdude.approvals import ApprovalPolicy
from codingdude.sandbox import build_sandbox_toolset, container_image_ready, docker_cli
from codingdude.tools import GateRequired

IMAGE = 'python:3.12-alpine'


def _probe_image(fn, image: str) -> bool:
    """Import-time docker probe, guarded (#368).

    A probe answers one question — may the container tests run? — so any
    failure means SKIP, and the exception is reported rather than swallowed.
    Unguarded, a 30s docker timeout here aborted collection of the entire
    suite: one slow daemon reddened the test job on a docs-only PR.
    """
    try:
        return fn(image)
    except Exception as exc:  # a probe must never abort collection
        warnings.warn(
            f'docker probe failed ({type(exc).__name__}: {exc}) — '
            f'container tests will skip', stacklevel=2)
        return False


docker_ready = _probe_image(container_image_ready, IMAGE)


def git(workdir, *args):
    subprocess.run(['git', *args], cwd=workdir, capture_output=True, check=True,
                   env={'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                        'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t',
                        'PATH': os.environ['PATH']})


@pytest.fixture
def repo(tmp_path):
    workdir = tmp_path / 'repo'
    workdir.mkdir()
    git(workdir, 'init', '-b', 'main')
    git(workdir, 'config', 'user.name', 't')
    git(workdir, 'config', 'user.email', 't@t')
    (workdir / 'base.txt').write_text('base\n')
    git(workdir, 'add', '.')
    git(workdir, 'commit', '-m', 'init')
    return workdir


def policy(**kw):
    return ApprovalPolicy(allowed_binaries=set(), **kw)


async def create_ok(toolset, name, **kw):
    """Create a sandbox and fail with the tool's own error text if it errs."""
    result = await toolset.tools['sandbox_create'].function(name=name, **kw)
    assert 'error:' not in result, result
    return result


async def test_create_reports_tier_preview_and_layout(repo):
    toolset = build_sandbox_toolset(repo, policy())
    result = await toolset.tools['sandbox_create'].function(
        name='proto', tier='worktree')
    assert 'tier=worktree+venv' in result
    assert 'preview=http://localhost:' in result
    box = repo / '.codingdude-worktrees' / 'proto'
    assert (box / 'base.txt').exists()
    assert (box / '.venv').is_dir()


async def test_create_existing_fails_cleanly(repo):
    toolset = build_sandbox_toolset(repo, policy())
    await create_ok(toolset, 'dup')
    result = await toolset.tools['sandbox_create'].function(name='dup')
    assert 'error:' in result


async def test_exec_runs_inside_sandbox_only(repo):
    toolset = build_sandbox_toolset(repo, policy(yolo=True))
    await create_ok(toolset, 'iso')
    result = await toolset.tools['sandbox_exec'].function(
        name='iso', command='python -c "open(\'made.txt\', \'w\').write(\'x\')"')
    assert 'exit 0' in result
    assert (repo / '.codingdude-worktrees' / 'iso' / 'made.txt').exists()
    assert not (repo / 'made.txt').exists()


async def test_exec_unknown_sandbox_is_readable(repo):
    toolset = build_sandbox_toolset(repo, policy())
    result = await toolset.tools['sandbox_exec'].function(
        name='ghost', command='python --version')
    assert 'error:' in result and 'ghost' in result


async def test_teardown_is_byte_identical(repo):
    toolset = build_sandbox_toolset(repo, policy())
    await create_ok(toolset, 'temp')
    def status():
        out = subprocess.run(['git', 'status', '--porcelain'], cwd=repo,
                             capture_output=True, text=True).stdout
        return [line for line in out.splitlines()
                if not line.endswith('.codingdude-worktrees/')]
    before = status()
    result = await toolset.tools['sandbox_teardown'].function(name='temp')
    after = status()
    assert after == before
    assert 'workdir clean' in result
    assert not (repo / '.codingdude-worktrees' / 'temp').exists()
    branches = subprocess.run(['git', 'branch', '--list', 'codingdude/temp'],
                              cwd=repo, capture_output=True, text=True)
    assert 'codingdude/temp' not in branches.stdout


async def test_promote_is_gated(repo):
    toolset = build_sandbox_toolset(repo, policy())
    await toolset.tools['sandbox_create'].function(name='feat')
    with pytest.raises(GateRequired):
        await toolset.tools['sandbox_promote'].function(
            name='feat', message='promote feat')


async def test_promote_merges_and_tears_down(repo):
    toolset = build_sandbox_toolset(repo, policy(yolo=True))
    await toolset.tools['sandbox_create'].function(name='feat')
    await toolset.tools['sandbox_exec'].function(
        name='feat',
        command='python -c "open(\'feature.txt\', \'w\').write(\'f\')"')
    box = repo / '.codingdude-worktrees' / 'feat'
    git(box, 'add', '-A')
    git(box, 'commit', '-m', 'feature')
    result = await toolset.tools['sandbox_promote'].function(
        name='feat', message='promote feat')
    assert 'promoted' in result
    assert (repo / 'feature.txt').read_text() == 'f'
    assert not (repo / '.codingdude-worktrees' / 'feat').exists()


# ---- tier 2: container ----


async def test_explicit_worktree_tier_wins_when_docker_exists(repo):
    if not docker_cli():
        pytest.skip('docker CLI not available')
    toolset = build_sandbox_toolset(repo, policy())
    result = await toolset.tools['sandbox_create'].function(
        name='t1', tier='worktree')
    assert 'tier=worktree+venv' in result


@pytest.mark.skipif(not docker_ready, reason='docker or image unavailable')
async def test_container_create_exec_and_teardown(repo):
    toolset = build_sandbox_toolset(repo, policy(yolo=True))
    result = await toolset.tools['sandbox_create'].function(
        name='box', tier='container')
    assert 'tier=container' in result
    assert f'image={IMAGE}' in result
    assert 'preview=http://localhost:' in result
    ps = subprocess.run(
        ['docker', 'ps', '--format', '{{.Names}}', '--filter',
         'name=codingdude-sb-box'], capture_output=True, text=True)
    assert 'codingdude-sb-box' in ps.stdout
    exec_result = await toolset.tools['sandbox_exec'].function(
        name='box', command='sh -c "touch made.txt"')
    assert 'exit 0' in exec_result
    assert (repo / '.codingdude-worktrees' / 'box' / 'made.txt').exists()
    dup = await toolset.tools['sandbox_create'].function(
        name='box', tier='container')
    assert 'error:' in dup
    teardown = await toolset.tools['sandbox_teardown'].function(name='box')
    assert 'workdir clean' in teardown
    ps_after = subprocess.run(
        ['docker', 'ps', '-a', '--format', '{{.Names}}',
         '--filter', 'name=codingdude-sb-box'],
        capture_output=True, text=True)
    assert 'codingdude-sb-box' not in ps_after.stdout
    assert not (repo / '.codingdude-worktrees' / 'box').exists()


async def test_container_tier_errors_when_docker_unusable(repo, monkeypatch):
    import codingdude.sandbox as sb
    monkeypatch.setattr(sb, 'docker_usable', lambda: False)
    toolset = build_sandbox_toolset(repo, policy())
    result = await toolset.tools['sandbox_create'].function(
        name='nx', tier='container')
    assert 'error:' in result and 'docker' in result.lower()
    assert not (repo / '.codingdude-worktrees' / 'nx').exists()


async def test_default_tier_prefers_worktree_without_docker(repo, monkeypatch):
    import codingdude.sandbox as sb
    monkeypatch.setattr(sb, 'docker_usable', lambda: False)
    toolset = build_sandbox_toolset(repo, policy())
    result = await toolset.tools['sandbox_create'].function(name='auto')
    assert 'tier=worktree+venv' in result


async def test_container_run_publishes_loopback_only(repo, monkeypatch):
    """Decision #98 container contracts, pinned at the sandbox_create seam:
    the preview port publishes loopback-only (never 0.0.0.0) and the
    creation argv passes no `-e` env flags (no host secrets in the
    container). No real docker needed: docker_cli points at a harmless
    binary (the ignored rm -f probe just exits nonzero) and the `docker run`
    call is captured at the run_captured boundary."""
    import sys

    import codingdude.sandbox as sb
    captured: dict[str, list[str]] = {}

    async def fake_run_captured(argv, **kw):
        captured['argv'] = list(argv)
        return types.SimpleNamespace(code=0, combined='abc123')

    monkeypatch.setattr(sb, 'docker_usable', lambda: True)
    monkeypatch.setattr(sb, 'docker_cli', lambda: sys.executable)
    monkeypatch.setattr(sb, 'run_captured', fake_run_captured)
    toolset = build_sandbox_toolset(repo, policy(yolo=True))
    result = await create_ok(toolset, 'lane', tier='container')
    argv = captured['argv']
    spec = argv[argv.index('-p') + 1]
    port = re.search(r'preview=http://localhost:(\d+)', result)
    assert port, result
    assert spec == f'127.0.0.1:{port.group(1)}:8000'
    assert '-e' not in argv


# ---- #368: a docker probe answers "no", it never raises ----
#
# These patch subprocess.run itself rather than sandbox's `subprocess` name:
# the except clause resolves subprocess.TimeoutExpired lazily, so swapping the
# module out from under it hides the very exception class under test.


def test_docker_usable_is_false_when_the_daemon_times_out(monkeypatch):
    """The exact CI failure: `docker info` timed out after 30s and escaped as
    TimeoutExpired instead of reporting 'docker unavailable'."""
    import codingdude.sandbox as sb

    def hang(argv, **kw):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=30)

    monkeypatch.setattr(sb, 'docker_cli', lambda: 'docker')
    monkeypatch.setattr(subprocess, 'run', hang)
    assert sb.docker_usable() is False


def test_docker_usable_is_false_when_the_cli_vanishes(monkeypatch):
    """A CLI that disappears between `which` and the call raises OSError —
    also a no, not a traceback."""
    import codingdude.sandbox as sb

    def gone(argv, **kw):
        raise FileNotFoundError(2, 'No such file or directory', argv[0])

    monkeypatch.setattr(sb, 'docker_cli', lambda: 'docker')
    monkeypatch.setattr(subprocess, 'run', gone)
    assert sb.docker_usable() is False


def test_docker_usable_still_says_yes_to_a_linux_daemon(monkeypatch):
    """Negative control: the guard must not swallow a healthy daemon."""
    import codingdude.sandbox as sb

    def answer(argv, **kw):
        out = 'linux' if 'info' in argv else '27.0.0'
        return subprocess.CompletedProcess(argv, 0, out, '')

    monkeypatch.setattr(sb, 'docker_cli', lambda: 'docker')
    monkeypatch.setattr(subprocess, 'run', answer)
    assert sb.docker_usable() is True


def test_image_probe_false_and_no_pull_when_inspect_hangs(monkeypatch):
    """An unanswerable inspect must not fall through to a pull: that would
    block against the same dead daemon for a second full timeout."""
    import codingdude.sandbox as sb

    seen: list[list[str]] = []

    def hang(argv, **kw):
        seen.append(list(argv))
        raise subprocess.TimeoutExpired(cmd=argv, timeout=30)

    monkeypatch.setattr(sb, 'docker_usable', lambda: True)
    monkeypatch.setattr(sb, 'docker_cli', lambda: 'docker')
    monkeypatch.setattr(subprocess, 'run', hang)
    assert sb.container_image_ready(IMAGE) is False
    assert [argv[:2] for argv in seen] == [['docker', 'image']]


def test_the_import_time_probe_degrades_to_skip():
    """#368, second half: a probe failure means SKIP — and says why. Unguarded
    it aborted collection of every test in the suite."""
    def explode(image):
        raise RuntimeError('daemon exploded')

    with pytest.warns(UserWarning, match='daemon exploded'):
        assert _probe_image(explode, IMAGE) is False


def test_the_import_time_probe_passes_a_clean_answer_through():
    """Negative control for the guard above: a working probe still decides."""
    assert _probe_image(lambda image: True, IMAGE) is True
