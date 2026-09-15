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


async def test_merge_gated_by_approvals(repo):
    """M11: worktree_merge mutates the main tree — with an interactive
    policy that denies, merge must not run git at all."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.worktrees import build_worktree_toolset

    policy = ApprovalPolicy(ask=_deny)
    toolset = build_worktree_toolset(repo, approvals=policy)
    import pytest as _pytest
    from pydantic_ai import ModelRetry, UnexpectedModelBehavior

    await toolset.tools['worktree_create'].function(name='m')
    with _pytest.raises((ModelRetry, UnexpectedModelBehavior)):
        await toolset.tools['worktree_merge'].function(name='m')


async def _deny(command):
    return 'deny'


async def test_merge_gated_headless_aborts(repo):
    """Headless (no ask callback): merge raises GateRequired per ADR-0003."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.tools import GateRequired
    from codingdude.worktrees import build_worktree_toolset

    toolset = build_worktree_toolset(repo, approvals=ApprovalPolicy())
    await toolset.tools['worktree_create'].function(name='m2')
    import pytest as _pytest

    with _pytest.raises(GateRequired):
        await toolset.tools['worktree_merge'].function(name='m2')


async def test_refactor_and_worktree_attached_in_build_all(tmp_path, monkeypatch):
    """M11: rename_symbol + worktree tools reach a real engine toolset."""
    from codingdude.config import Config
    from codingdude.db import Database
    from codingdude.plugins import PluginContext, build_all

    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr('codingdude.mcp_config.ensure_default_mcp', lambda *_: None)
    monkeypatch.setattr('codingdude.plugins.merged_mcp_server_names', lambda *_: [])
    ctx = PluginContext(
        workdir=tmp_path, config=Config.defaults(), db=Database.connect(home),
        session_id='s11', home=home,
    )
    toolsets = await build_all(ctx)
    names = {t.name for ts in toolsets for t in getattr(ts, 'tools', {}).values()}
    assert {'rename_symbol', 'worktree_create', 'worktree_merge', 'worktree_list'} <= names


def test_remove_worktree_cleans_branch_and_dir(repo):
    from codingdude.worktrees import create_worktree, remove_worktree

    create_worktree(repo, 'rm-me')
    assert (repo / '.codingdude-worktrees' / 'rm-me').exists()
    remove_worktree(repo, 'rm-me')
    assert not (repo / '.codingdude-worktrees' / 'rm-me').exists()
    import subprocess
    branches = subprocess.run(['git', 'branch', '--list', 'codingdude/rm-me'],
                              cwd=repo, capture_output=True, text=True)
    assert branches.stdout.strip() == ''
