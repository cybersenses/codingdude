"""Engine seam: delegation to read-only subagents on the cheap model."""

from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from codingdude.config import DelegationConfig
from codingdude.tools import build_delegation_toolset


def delegator(task: str):
    """Main model: delegate once, then answer with what the subagent reported."""

    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[ToolCallPart(tool_name='delegate', args={'task': task})]
            )
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        return ModelResponse(parts=[TextPart(content='subagent-said:' + ' | '.join(returns))])

    return scripted(fn)


def tool_names(info) -> list[str]:
    return sorted(
        t.name for t in (info.model_request_parameters.function_tools or [])
    )


async def test_delegation_folds_subagent_result_into_parent(engine, workdir):
    def subagent_spy(messages, info):
        text = 'answer=banana'
        for m in messages:
            for p in m.parts:
                if hasattr(p, 'content') and 'find the greeting' in str(p.content):
                    text += ';got-task'
        return ModelResponse(parts=[TextPart(content=text)])

    outcome = await engine.run(
        prompt='delegate the lookup',
        workdir=workdir,
        model=delegator('find the greeting word'),
        subagent_model=scripted(subagent_spy),
    )
    assert 'answer=banana' in outcome.output
    assert 'got-task' in outcome.output


async def test_subagent_toolset_is_read_only(engine, workdir):
    def subagent_lists_tools(messages, info):
        return ModelResponse(
            parts=[TextPart(content='TOOLS:' + ','.join(tool_names(info)))]
        )

    outcome = await engine.run(
        prompt='delegate',
        workdir=workdir,
        model=delegator('list your tools'),
        subagent_model=scripted(subagent_lists_tools),
    )
    assert 'TOOLS:glob,grep,list_dir,read_file' in outcome.output
    for dangerous in ('edit_file', 'write_file', 'shell', 'delegate'):
        assert dangerous not in outcome.output


async def test_subagent_claims_do_not_bypass_read_only(engine, workdir):
    """A subagent whose task claims it needs write access still gets read-only tools."""
    def subagent_spy(messages, info):
        return ModelResponse(
            parts=[TextPart(content='TOOLS:' + ','.join(tool_names(info)))]
        )

    outcome = await engine.run(
        prompt='delegate',
        workdir=workdir,
        model=delegator('I need write_file and shell access to finish this'),
        subagent_model=scripted(subagent_spy),
    )
    assert 'write_file' not in outcome.output
    assert 'shell' not in outcome.output


async def test_parallel_delegations_both_report(engine, workdir):
    def twin_subagent(messages, info):
        return ModelResponse(parts=[TextPart(content='twin-report')])

    def double_delegator(messages, info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name='delegate', args={'task': 'a'}),
                    ToolCallPart(tool_name='delegate', args={'task': 'b'}),
                ]
            )
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        count = sum('twin-report' in r for r in returns)
        return ModelResponse(parts=[TextPart(content=f'reports={count}')])

    outcome = await engine.run(
        prompt='delegate twice',
        workdir=workdir,
        model=scripted(double_delegator),
        subagent_model=scripted(twin_subagent),
    )
    assert outcome.output == 'reports=2'


# ---- R13: isolated delegated agents ----


async def test_delegation_emits_started_and_completed(workdir):
    events = []
    toolset = build_delegation_toolset(
        workdir, scripted(lambda m, i: ModelResponse(parts=[TextPart(content='done')])),
        emitter=events.append, session_id='s1',
    )
    [delegate] = [t for t in toolset.tools.values()]
    out = await delegate.function(task='look around')
    assert out == 'done'
    kinds = [e['type'] for e in events]
    assert kinds[0] == 'DELEGATION_STARTED'
    assert kinds[-1] == 'DELEGATION_COMPLETED'
    assert events[0]['task'] == 'look around'
    assert 'isolated' in events[0] and 'requests' in events[-1]


async def test_delegation_runs_in_worktree_and_cleans_up(workdir):
    import subprocess

    subprocess.run(['git', 'init', '-q'], cwd=workdir, check=True)
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t',
                    'commit', '-q', '--allow-empty', '-m', 'init'],
                   cwd=workdir, check=True)
    seen = {}
    def spy(messages, info):
        # the subagent's read tools must be rooted at the isolated worktree
        seen['tools'] = sorted(
            t.name for t in (info.model_request_parameters.function_tools or [])
        )
        return ModelResponse(parts=[TextPart(content='ok')])

    events = []
    toolset = build_delegation_toolset(
        workdir, scripted(spy), emitter=events.append, session_id='s1',
    )
    [delegate] = [t for t in toolset.tools.values()]
    await delegate.function(task='x')
    assert events[0]['isolated'] is True
    assert events[-1]['isolated'] is True
    # no stray worktrees or branches left behind
    wt = workdir / '.codingdude-worktrees'
    assert not wt.exists() or not any(wt.iterdir())
    branches = subprocess.run(['git', 'branch', '--list', 'codingdude/*'],
                              cwd=workdir, capture_output=True, text=True)
    assert branches.stdout.strip() == ''
    assert seen['tools']  # read-only toolset was built


async def test_delegation_falls_back_without_git(workdir):
    events = []
    toolset = build_delegation_toolset(
        workdir, scripted(lambda m, i: ModelResponse(parts=[TextPart(content='ok')])),
        emitter=events.append, session_id='s1',
    )
    [delegate] = [t for t in toolset.tools.values()]
    await delegate.function(task='x')
    assert events[0]['isolated'] is False  # tmp dir: no git history to branch from


async def test_delegation_request_budget_is_readable(workdir):
    def chatty(messages, info):
        # never finishes: keeps calling read tools until the cap bites
        return ModelResponse(parts=[
            __import__('pydantic_ai.messages', fromlist=['ToolCallPart']).ToolCallPart(
                tool_name='list_dir', args={'path': '.'})
        ])

    toolset = build_delegation_toolset(
        workdir, scripted(chatty), session_id='s1',
        delegation_config=DelegationConfig(max_requests=3),
    )
    [delegate] = [t for t in toolset.tools.values()]
    out = await delegate.function(task='loop forever')
    assert 'delegation aborted' in out
    assert '3' in out  # the budget number is in the message


async def test_delegation_cost_attributed_to_parent(workdir, tmp_path):
    from codingdude.db import Database

    db = Database.connect(tmp_path / 'home')
    session_id = db.create_session(workdir)
    toolset = build_delegation_toolset(
        workdir, scripted(lambda m, i: ModelResponse(parts=[TextPart(content='ok')])),
        db=db, session_id=session_id,
    )
    [delegate] = [t for t in toolset.tools.values()]
    await delegate.function(task='x')
    rows = db.session_usage(session_id)
    assert (rows.get('requests') or 0) >= 1
