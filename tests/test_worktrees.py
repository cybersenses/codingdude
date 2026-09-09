"""Worktree isolation: create, list, merge lifecycle via git."""

import subprocess

import pytest

from codingdude.worktrees import build_worktree_toolset


def git(workdir, *args):
    subprocess.run(['git', *args], cwd=workdir, capture_output=True, check=True,
                   env={'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                        'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t',
                        'PATH': __import__('os').environ['PATH']})


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


async def test_create_worktree(repo):
    toolset = build_worktree_toolset(repo)
    result = await toolset.tools['worktree_create'].function(name='feature')
    assert 'worktree ready' in result
    assert (repo / '.codingdude-worktrees' / 'feature' / 'base.txt').exists()
    branch = subprocess.run(['git', 'branch', '--list', 'codingdude/feature'],
                            cwd=repo, capture_output=True, text=True)
    assert 'codingdude/feature' in branch.stdout


async def test_create_existing_fails_cleanly(repo):
    toolset = build_worktree_toolset(repo)
    await toolset.tools['worktree_create'].function(name='dup')
    result = await toolset.tools['worktree_create'].function(name='dup')
    assert 'error:' in result


async def test_no_commits_fails_cleanly(tmp_path):
    toolset = build_worktree_toolset(tmp_path)
    result = await toolset.tools['worktree_create'].function(name='x')
    assert 'initial commit' in result


async def test_list_worktrees(repo):
    toolset = build_worktree_toolset(repo)
    await toolset.tools['worktree_create'].function(name='listed')
    listing = await toolset.tools['worktree_list'].function()
    assert 'listed' in listing
