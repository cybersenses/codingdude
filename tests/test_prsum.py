"""R33 #66: PR summary generation from git log/diff + AST semantic summaries."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from codingdude.approvals import ApprovalPolicy  # noqa: E402
from codingdude.prsum import pr_summary  # noqa: E402
from codingdude.tools import build_git_toolset  # noqa: E402


def _tool(toolset, name):
    return toolset.tools[name].function


def git(workdir: Path, *args: str) -> None:
    import os

    subprocess.run(
        ['git', *args], cwd=workdir, check=True, capture_output=True,
        env={**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
             'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'},
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.name', 'test')
    git(tmp_path, 'config', 'user.email', 'test@test')
    (tmp_path / 'mod.py').write_text('def old():\n    return 1\n')
    (tmp_path / 'notes.md').write_text('# notes\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'init')
    git(tmp_path, 'branch', 'base')  # marker for base ref
    return tmp_path


def test_new_python_file_lists_added_symbols(repo: Path) -> None:
    (repo / 'newmod.py').write_text('def greet(name):\n    return f"hi {name}"\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'add greet')
    out = pr_summary(repo, base='base')
    assert 'add greet' in out  # commit subject
    assert 'newmod.py' in out  # diff stat
    assert 'added greet' in out  # AST semantic summary


def test_signature_change_is_reported(repo: Path) -> None:
    (repo / 'mod.py').write_text('def old(x):\n    return x\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'change signature')
    out = pr_summary(repo, base='base')
    assert 'changed body of old' in out or 'signature' in out


def test_non_python_change_omits_ast_section(repo: Path) -> None:
    (repo / 'notes.md').write_text('# more\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'docs only')
    out = pr_summary(repo, base='base')
    assert 'docs only' in out
    assert 'added' not in out


def test_pr_summary_tool_registered(repo: Path) -> None:
    fn = _tool(build_git_toolset(repo, ApprovalPolicy()), 'pr_summary')
    import asyncio

    (repo / 'notes.md').write_text('# tool test\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'tool test')
    out = asyncio.run(fn(base='base'))
    assert 'tool test' in out
