"""R17: write-capable delegation — exec_in_sandbox with diff reporting."""

from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from codingdude.approvals import ApprovalPolicy

POLICY = ApprovalPolicy(yolo=True)


def _git(workdir, *args):
    import subprocess
    return subprocess.run(['git', *args], cwd=workdir, capture_output=True,
                          text=True)


def _init_repo(workdir):
    _git(workdir, 'init', '-q')
    _git(workdir, '-c', 'user.email=t@t', '-c', 'user.name=t',
         'commit', '-q', '--allow-empty', '-m', 'init')


def delegator(call_args):
    """Model that plays the parent: one delegate call, then a final answer."""
    state = {'called': False}

    def fn(messages: list[ModelMessage], info):
        if not state['called']:
            state['called'] = True
            return ModelResponse(parts=[
                ToolCallPart(tool_name='delegate', args=call_args)])
        returns = [
            str(p.content) for m in messages for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        return ModelResponse(parts=[TextPart(content='parent:' + ' | '.join(returns))])

    return scripted(fn)


def sub_script(steps):
    """Scripted subagent: first turn inspects tools or execs, second answers."""
    state = {'n': 0}

    def fn(messages: list[ModelMessage], info):
        state['n'] += 1
        if state['n'] == 1:
            if steps.get('report_tools'):
                names = sorted(
                    t.name for t in
                    (info.model_request_parameters.function_tools or []))
                return ModelResponse(
                    parts=[TextPart(content='TOOLS:' + ','.join(names))])
            return ModelResponse(parts=[
                ToolCallPart(tool_name='exec_in_sandbox',
                             args={'command': steps['command']})])
        returns = [
            str(p.content) for m in messages for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        return ModelResponse(parts=[TextPart(content='sub:' + ' | '.join(returns))])

    return scripted(fn)


async def test_default_delegation_has_no_exec_tool(engine, workdir):
    _init_repo(workdir)
    outcome = await engine.run(
        prompt='delegate', workdir=workdir,
        model=delegator({'task': 't'}),
        subagent_model=sub_script({'report_tools': True}),
    )
    assert 'TOOLS:glob,grep,list_dir,read_file' in outcome.output


async def test_write_delegation_exposes_exec_tool(engine, workdir):
    _init_repo(workdir)
    outcome = await engine.run(
        prompt='delegate', workdir=workdir,
        model=delegator({'task': 't', 'write': True}), approvals=POLICY,
        subagent_model=sub_script({'report_tools': True}),
    )
    tools_line = outcome.output.split('TOOLS:')[1].split('\n')[0]
    assert 'exec_in_sandbox' in tools_line
    for dangerous in ('edit_file', 'write_file', 'shell', 'sandbox_promote'):
        assert dangerous not in tools_line


async def test_exec_in_sandbox_runs_in_sandbox_and_reports_diff(engine, workdir):
    _init_repo(workdir)
    outcome = await engine.run(
        prompt='delegate', workdir=workdir,
        model=delegator({'task': 'try a change', 'write': True}), approvals=POLICY,
        subagent_model=sub_script({'command': 'echo hi > probe.txt'}),
    )
    out = outcome.output
    assert 'sub:exit 0' in out, out
    assert 'Sandbox diff' in out and 'probe.txt' in out
    # the main tree is untouched; the write landed only in the (torn-down)
    # sandbox worktree
    assert not (workdir / 'probe.txt').exists()
    wt = workdir / '.codingdude-worktrees'
    assert not wt.exists() or not any(wt.iterdir())


async def test_write_delegation_without_git_errors_exec(engine, workdir):
    """No git history: no isolated sandbox, so exec must error, not touch main."""
    outcome = await engine.run(
        prompt='delegate', workdir=workdir,
        model=delegator({'task': 't', 'write': True}), approvals=POLICY,
        subagent_model=sub_script({'command': 'echo pwned > pwned.txt'}),
    )
    assert 'error: no sandbox named' in outcome.output
    assert not (workdir / 'pwned.txt').exists()


async def test_write_delegation_clean_tree_reports_no_diff(engine, workdir):
    _init_repo(workdir)

    def quiet(messages, info):
        return ModelResponse(parts=[TextPart(content='nothing tried')])

    outcome = await engine.run(
        prompt='delegate', workdir=workdir,
        model=delegator({'task': 'look only', 'write': True}), approvals=POLICY,
        subagent_model=scripted(quiet),
    )
    assert 'sandbox tree clean' in outcome.output
