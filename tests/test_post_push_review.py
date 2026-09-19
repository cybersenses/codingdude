"""R33 #67: post-push auto code-review directive.

After a successful push, the git_push tool must return the pushed range and
an instruction to run the review loop (review -> verify findings -> fix ->
gates -> commit). Push itself stays always-gated; the directive only guides
what the agent does next.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from codingdude.approvals import ApprovalPolicy  # noqa: E402
from codingdude.tools import build_git_toolset  # noqa: E402


def _tool(toolset, name):
    return toolset.tools[name].function


def git(workdir: Path, *args: str) -> str:
    return subprocess.run(
        ['git', *args], cwd=workdir, check=True, capture_output=True, text=True,
        env={**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
             'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'},
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-b', 'main', str(remote)], check=True,
                   capture_output=True)
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo.parent, 'init', '-b', 'main', 'repo')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@test')
    (repo / 'a.py').write_text('def a():\n    return 1\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'init')
    git(repo, 'remote', 'add', 'origin', str(remote))
    return repo


def test_push_returns_review_directive_with_range(repo: Path) -> None:
    fn = _tool(build_git_toolset(repo, ApprovalPolicy(yolo=True)), 'git_push')
    assert 'exit 0' in asyncio.run(fn())  # initial push
    git(repo, 'fetch', 'origin')
    old_head = git(repo, 'rev-parse', 'origin/main')
    (repo / 'a.py').write_text('def a(x):\n    return x\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'change a')
    out = asyncio.run(fn())
    assert 'exit 0' in out
    assert 'review' in out.lower()
    assert old_head in out  # pushed range base is the pre-push remote head


def test_first_push_directive_without_range(repo: Path) -> None:
    # Simulate a first push: no remote-tracking ref exists yet.
    ref = repo / '.git' / 'refs' / 'remotes' / 'origin'
    if ref.exists():
        for f in ref.rglob('*'):
            if f.is_file():
                f.unlink()
    fn = _tool(build_git_toolset(repo, ApprovalPolicy(yolo=True)), 'git_push')
    out = asyncio.run(fn())
    assert 'exit 0' in out
    assert 'review' in out.lower()
    assert 'first push' in out


def test_failed_push_has_no_directive(repo: Path) -> None:
    # Break the remote so push fails.
    (repo / '.git' / 'hooks' / 'pre-push').write_text('#!/bin/sh\nexit 1\n')
    fn = _tool(build_git_toolset(repo, ApprovalPolicy(yolo=True)), 'git_push')
    out = asyncio.run(fn())
    assert 'exit 0' not in out
    assert 'review' not in out.lower()
