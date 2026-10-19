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
import subprocess

import pytest

from codingdude.approvals import ApprovalPolicy
from codingdude.sandbox import build_sandbox_toolset, container_image_ready, docker_cli
from codingdude.tools import GateRequired

IMAGE = 'python:3.12-alpine'

docker_ready = container_image_ready(IMAGE)


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
