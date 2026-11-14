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
"""R92 #339: pre-push review is a gate, not a convention.

Pre-push two-axis review was mandated in project notes but enforced nowhere:
`.git/hooks` is empty, `gates.bat` runs only ruff/mypy/pytest, and the sole
nudge was a string appended to the push output — after the irreversible act.
These tests pin the gate: a push needs a recorded review of the exact diff
being pushed.

Also pinned: the old review seam ran `git diff HEAD`, which is empty once work
is committed — i.e. a pre-push review reviewed nothing and called it CLEAN.
"""

import asyncio
import os
import subprocess  # nosec B404 - git in a temp fixture repo, fixed argv
import sys
from pathlib import Path

import pytest
from pydantic_ai import ModelRetry

sys.path.insert(0, str(Path(__file__).parent))

from codingdude.approvals import ApprovalPolicy  # noqa: E402
from codingdude.review_gate import (  # noqa: E402
    EMPTY_TREE,
    ReviewGateError,
    collect_review_diff,
    record_review,
    require_review,
    resolve_base,
    review_diff_key,
)
from codingdude.tools import (  # noqa: E402
    _is_direct_git_push,
    build_git_toolset,
    build_shell_toolset,
    build_toolset,
)


def _tool(toolset, name):
    return toolset.tools[name].function


def git(workdir: Path, *args: str) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ['git', *args], cwd=workdir, check=True, capture_output=True, text=True,
        env={**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
             'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'},
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / 'remote.git'
    subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ['git', 'init', '--bare', '-b', 'main', str(remote)], check=True,
        capture_output=True,
    )
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo.parent, 'init', '-b', 'main', 'repo')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@test')
    (repo / 'a.py').write_text('def a():\n    return 1\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'init')
    git(repo, 'remote', 'add', 'origin', str(remote))
    # Publish a reviewed baseline so `origin/main` exists and the range diff is
    # meaningful (without it base resolution silently degrades to the work tree).
    tools = build_git_toolset(repo, ApprovalPolicy(yolo=True))
    asyncio.run(tools.tools['record_review'].function(
        standards='baseline', spec='baseline',
    ))
    assert 'exit 0' in asyncio.run(tools.tools['git_push'].function())
    git(repo, 'fetch', 'origin')
    return repo


def _tools(repo: Path):
    return build_git_toolset(repo, ApprovalPolicy(yolo=True))


def _record(tools) -> str:
    fn = _tool(tools, 'record_review')
    return asyncio.run(fn(
        standards='no findings — 40 lines, reuses _run, no new abstraction',
        spec='no findings — ticket #339 items 1-3 all present',
    ))


def _commit_change(repo: Path, body: str = 'def a(x):\n    return x\n') -> None:
    (repo / 'a.py').write_text(body)
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'change a')


def test_push_refused_without_review(repo: Path) -> None:
    """The gate: an unreviewed push never reaches the remote."""
    tools = _tools(repo)
    before = git(repo, 'ls-remote', 'origin', 'refs/heads/main')
    record = repo / '.git' / 'codingdude' / 'review.json'
    record.unlink()  # the state the gate exists for: no review on record
    _commit_change(repo)
    with pytest.raises(ModelRetry) as err:
        asyncio.run(_tool(tools, 'git_push')())
    assert 'pre-push review' in str(err.value)
    assert git(repo, 'ls-remote', 'origin', 'refs/heads/main') == before


def test_push_allowed_after_recorded_review(repo: Path) -> None:
    tools = _tools(repo)
    _commit_change(repo)
    _record(tools)
    assert 'exit 0' in asyncio.run(_tool(tools, 'git_push')())


def test_record_requires_both_axes(repo: Path) -> None:
    """Half a review is not a review — the #293 evidence shape, applied here."""
    tools = _tools(repo)
    _commit_change(repo)
    with pytest.raises(ModelRetry) as err:
        asyncio.run(_tool(tools, 'record_review')(
            standards='no findings', spec='   ',
        ))
    assert 'spec_evidence' in str(err.value)


def test_diff_changed_after_review_is_refused(repo: Path) -> None:
    """Fixing findings after the review voids it — you review what you push."""
    tools = _tools(repo)
    _commit_change(repo)
    _record(tools)
    _commit_change(repo, 'def a(x, y):\n    return x + y\n')
    with pytest.raises(ModelRetry) as err:
        asyncio.run(_tool(tools, 'git_push')())
    assert 'changed since the review' in str(err.value)


def test_amend_with_identical_content_keeps_review_valid(repo: Path) -> None:
    """Content-addressed: rewriting the message does not demand a re-review."""
    tools = _tools(repo)
    _commit_change(repo)
    before = git(repo, 'rev-parse', 'HEAD')
    _record(tools)
    git(repo, 'commit', '--amend', '-m', 'change a (message rewritten)')
    assert git(repo, 'rev-parse', 'HEAD') != before  # different commit, same diff
    assert 'exit 0' in asyncio.run(_tool(tools, 'git_push')())


def test_working_tree_edit_after_review_is_refused(repo: Path) -> None:
    """Uncommitted edits are published content too."""
    tools = _tools(repo)
    _commit_change(repo)
    _record(tools)
    (repo / 'a.py').write_text('def a(x, y, z):\n    return x + y + z\n')
    with pytest.raises(ModelRetry):
        asyncio.run(_tool(tools, 'git_push')())


def test_review_diff_includes_committed_range(repo: Path) -> None:
    """The old seam reviewed `git diff HEAD` — empty right after a commit."""
    _commit_change(repo)
    assert git(repo, 'diff', 'HEAD') == ''  # nothing left in the work tree
    diff = collect_review_diff(repo, base='HEAD~1')
    assert 'def a(x):' in diff  # ...yet the commit is what a review must see


def test_base_is_resolved_not_caller_chosen(tmp_path: Path) -> None:
    """A caller-chosen base was the bypass: `base='HEAD'` reviewed nothing.

    With no remote ref yet, the gate reviews the branch against the empty tree,
    so the range carries the branch's whole content instead of an empty string.
    """
    local = tmp_path / 'local'
    local.mkdir()
    git(local.parent, 'init', '-b', 'main', 'local')
    git(local, 'config', 'user.name', 't')
    git(local, 'config', 'user.email', 't@t')
    (local / 'a.py').write_text('def a():\n    return 1\n')
    git(local, 'add', '.')
    git(local, 'commit', '-m', 'init')
    assert resolve_base(local) == EMPTY_TREE  # no origin/main to merge-base
    assert 'def a():' in collect_review_diff(local)  # content, not an empty range


def test_review_of_baseline_does_not_cover_later_commits(tmp_path: Path) -> None:
    """The fail-open case: a record matching an empty range must not survive."""
    local = tmp_path / 'local'
    local.mkdir()
    git(local.parent, 'init', '-b', 'main', 'local')
    git(local, 'config', 'user.name', 't')
    git(local, 'config', 'user.email', 't@t')
    (local / 'a.py').write_text('def a():\n    return 1\n')
    git(local, 'add', '.')
    git(local, 'commit', '-m', 'init')
    reviewed = record_review(
        local, standards_evidence='test', spec_evidence='test',
    )['diff_key']
    (local / 'a.py').write_text('def a(x):\n    return x\n')
    git(local, 'add', '.')
    git(local, 'commit', '-m', 'change a')
    assert review_diff_key(local) != reviewed
    with pytest.raises(ReviewGateError):
        require_review(local)


def test_other_branch_tip_is_not_covered_by_a_head_review(repo: Path) -> None:
    """Reviewed content is HEAD's diff; pushing another ref needs its own review."""
    _commit_change(repo)
    _record(_tools(repo))
    git(repo, 'branch', 'feature', 'HEAD~1')
    with pytest.raises(ReviewGateError) as err:
        require_review(repo, 'feature')
    assert 'recorded review covers' in str(err.value)


def test_shell_refuses_a_direct_git_push(repo: Path) -> None:
    """The shell is a second route to the remote — it must not bypass the gate."""
    shell = build_shell_toolset(repo, ApprovalPolicy(yolo=True)).tools['shell']
    with pytest.raises(ModelRetry) as err:
        asyncio.run(shell.function('git push origin main'))
    assert 'pre-push review gate' in str(err.value)
    assert not _is_direct_git_push('git status --porcelain')


def test_file_tools_cannot_write_inside_the_git_dir(repo: Path) -> None:
    """Writing the record directly would fabricate a review."""
    tools = build_toolset(repo)
    with pytest.raises(ModelRetry) as err:
        tools.tools['write_file'].function(
            '.git/codingdude/review.json', '{"diff_key": "x"}',
        )
    assert 'git directory' in str(err.value)
    assert tools.tools['edit_file'].function  # surfaced, not silently stripped
