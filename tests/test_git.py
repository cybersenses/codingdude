"""Engine seam: git/gh tools — reads auto, commit/branch gated, push/PR always-gated."""

import subprocess

from helpers import scripted

from codingdude.approvals import ApprovalPolicy
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


def git(workdir, *args):
    subprocess.run(
        ['git', *args], cwd=workdir, check=True, capture_output=True,
        env={'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
             'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t',
             'GIT_AUTHOR_DATE': '2005-04-07T22:13:13', 'GIT_COMMITTER_DATE': '2005-04-07T22:13:13',
             'PATH': __import__('os').environ['PATH'], 'SYSTEMROOT': __import__('os').environ.get('SYSTEMROOT', '')},
    )


def git_repo(workdir):
    git(workdir, 'init', '-b', 'main')
    git(workdir, 'config', 'user.name', 'test')
    git(workdir, 'config', 'user.email', 'test@test')
    (workdir / 'hello.txt').write_text('hello\n')
    git(workdir, 'add', '.')
    git(workdir, 'commit', '-m', 'init')


def tool_then_answer(tool_name: str, args: dict, check):
    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=args)])
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, (ToolReturnPart, TextPart))
        ]
        return ModelResponse(parts=[TextPart(content=check('\n'.join(returns)))])

    return scripted(fn)


async def test_git_status_reads_auto(engine, workdir):
    git_repo(workdir)
    outcome = await engine.run(
        prompt='repo state?',
        workdir=workdir,
        approvals=ApprovalPolicy(),
        model=tool_then_answer(
            'git_status', {}, lambda r: 'clean-ish' if 'hello.txt' in r or 'main' in r else r[:200]
        ),
    )
    assert outcome.output == 'clean-ish'


async def test_commit_is_gated_and_approval_lets_it_through(engine, workdir):
    git_repo(workdir)
    (workdir / 'hello.txt').write_text('hello world\n')

    # Without a pattern approval: gate abort with the commit visible in the report.
    outcome = await engine.run(
        prompt='commit',
        workdir=workdir,
        approvals=ApprovalPolicy(),
        model=tool_then_answer(
            'git_commit', {'message': 'update hello'}, lambda r: 'should-not-finish'
        ),
    )
    assert outcome.status == 'gate_aborted'

    # Approve the pattern → commit lands.
    engine.approve_pattern(outcome.session_id, 'git commit')
    outcome2 = await engine.run(
        prompt='commit',
        workdir=workdir,
        session_id=outcome.session_id,
        approvals=ApprovalPolicy(),
        model=tool_then_answer(
            'git_commit', {'message': 'update hello'}, lambda r: 'committed' if 'committed' in r else r[:200]
        ),
    )
    assert outcome2.output == 'committed'
    log = subprocess.run(['git', 'log', '--oneline'], cwd=workdir, capture_output=True, text=True)
    assert 'update hello' in log.stdout


async def test_push_and_pr_always_gated(engine, workdir):
    git_repo(workdir)
    policy = ApprovalPolicy()
    # Even a matching pattern never unlocks the always-gated tier.
    policy.approve_pattern('git push')
    outcome = await engine.run(
        prompt='push',
        workdir=workdir,
        approvals=policy,
        model=tool_then_answer(
            'git_push', {'remote': 'origin', 'branch': 'main'}, lambda r: 'should-not-run'
        ),
    )
    assert outcome.status == 'gate_aborted'
    assert 'git push' in outcome.gate.command or 'push' in outcome.gate.command


async def test_gh_pr_reports_stub(engine, workdir, monkeypatch):
    """The gh PR flow works end-to-end against a stubbed gh binary."""
    (workdir / 'gh.bat').write_text('@echo off\necho PR 42: https://example.com/pr/42\n')

    git_repo(workdir)
    engine.approve_pattern(engine._db.create_session(workdir, title='t'), 'gh_pr_create')

    policy = ApprovalPolicy()
    outcome = await engine.run(
        prompt='make a pr',
        workdir=workdir,
        approvals=policy,
        model=tool_then_answer(
            'gh_pr_create',
            {'title': 'T', 'body': 'B'},
            lambda r: 'pr-ok' if 'PR 42' in r else r[:200],
        ),
    )
    assert outcome.status == 'gate_aborted'  # always-gated: pattern can't unlock

    # With explicit consent (--yolo) the stubbed gh actually runs.
    outcome2 = await engine.run(
        prompt='make a pr',
        workdir=workdir,
        approvals=ApprovalPolicy(yolo=True),
        model=tool_then_answer(
            'gh_pr_create',
            {'title': 'T', 'body': 'B'},
            lambda r: 'pr-ok' if 'PR 42' in r else r[:200],
        ),
    )
    assert outcome2.output == 'pr-ok'
