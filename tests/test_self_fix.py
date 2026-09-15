"""Regression tests for self-fix tranche 2 (H3/H4/H8/M2/M6).

Each test fails on the pre-fix code and passes after the fix; they pin the
Workdir boundary and the documented-config behaviours that were broken.
"""

import pytest
from pydantic_ai import ModelRetry

from codingdude.approvals import ApprovalPolicy
from codingdude.config import load_project_config
from codingdude.deadcode import build_deadcode_toolset
from codingdude.tools import build_coverage_toolset, build_toolset


def _fn(toolset, name):
    return toolset.tools[name].function


async def test_h3_run_coverage_rejects_escaping_source(workdir):
    """`source` must stay a relative in-Workdir path (no shell injection)."""
    run_coverage = _fn(build_coverage_toolset(workdir, ApprovalPolicy()), 'run_coverage')
    with pytest.raises(ModelRetry):
        await run_coverage(source='../..')
    with pytest.raises(ModelRetry):
        await run_coverage(source='src/../..')


def test_h4_project_shell_documented_shape(workdir):
    """The documented `shell = "powershell"` form must take effect (issue 04)."""
    (workdir / '.codingdude.toml').write_text('shell = "powershell"\n', encoding='utf-8')
    assert load_project_config(workdir) == {'shell': 'powershell'}


async def test_h8_deadcode_is_workdir_confined(workdir):
    """find_dead_code must refuse paths outside the Workdir."""
    find_dead_code = _fn(build_deadcode_toolset(workdir), 'find_dead_code')
    with pytest.raises(ModelRetry):
        await find_dead_code(path='../../..')


def test_m2_glob_refuses_escaping_pattern(workdir):
    """glob() must refuse patterns that climb out of the Workdir."""
    glob = _fn(build_toolset(workdir, read_only=True), 'glob')
    with pytest.raises(ModelRetry):
        glob('../../*.py')


def test_m6_delete_session_removes_plans(db, workdir):
    """Deleting a Session must not orphan its plans rows."""
    sid = db.create_session(workdir)
    db._conn.execute(
        "INSERT INTO plans (session_id, goal, steps, status, created_at)"
        " VALUES (?, 'g', '[]', 'approved', 'now')",
        (sid,),
    )
    db._conn.commit()
    db.delete_session(sid)
    remaining = db._conn.execute(
        'SELECT COUNT(*) AS c FROM plans WHERE session_id = ?', (sid,)
    ).fetchone()['c']
    assert remaining == 0


def test_h5_worker_forwards_vision_model():
    """The worker must forward the configured vision model to the engine."""
    from codingdude.worker import engine_run_kwargs

    class Args:
        prompt = 'p'
        workdir = '.'
        session = 's'
        fix_loop = False
        image = None

    assert engine_run_kwargs(Args(), None)['vision_model'] is None
    assert engine_run_kwargs(Args(), None, 'zai:glm-5v')['vision_model'] == 'zai:glm-5v'


def test_h5_image_extension_sniffs_media_type():
    """A JPEG upload must not be mislabelled PNG (server-side sniff)."""
    from codingdude.server import _image_extension

    assert _image_extension(b'\x89PNG\r\n\x1a\nrest') == '.png'
    assert _image_extension(b'\xff\xd8\xff\xe0rest') == '.jpg'


async def test_h6_aux_model_usage_is_recorded(engine, workdir):
    """Memory extraction is billed to the session, not lost (H6)."""
    from helpers import say, scripted

    engine._extraction_model = scripted(say('- the project uses uv'))
    outcome = await engine.run(prompt='hello', workdir=workdir, model=scripted(say('done')))
    await engine.drain_post_run()  # extraction usage is recorded in the background tail
    assert engine._db.session_usage(outcome.session_id)['requests'] >= 2


def test_m10_shell_argv_selects_the_configured_shell():
    """One helper drives bash vs powershell (no hardcoded bash) (M10)."""
    from codingdude.tools import shell_argv

    assert shell_argv('ls -la', 'bash') == ['bash', '-c', 'ls -la']
    assert shell_argv('Get-ChildItem', 'powershell') == [
        'powershell', '-NoProfile', '-Command', 'Get-ChildItem'
    ]


def test_m8_project_can_reenable_a_globally_disabled_server(home, workdir):
    """A project `enabled` entry must override a global `disabled` (M8)."""
    import json

    from codingdude.mcp_config import merged_mcp_config, set_mcp_disabled

    home.mkdir(parents=True, exist_ok=True)
    (home / 'mcp.json').write_text(
        json.dumps({'mcpServers': {'x': {'command': 'x'}}, 'disabled': ['x']})
    )
    (workdir / '.codingdude').mkdir(parents=True, exist_ok=True)
    assert merged_mcp_config(home, workdir)['disabled'] == ['x']
    assert set_mcp_disabled(home, workdir, 'x', disabled=False) is True
    assert merged_mcp_config(home, workdir)['disabled'] == []


def test_m14_typescript_files_use_the_ts_grammar():
    """TS-only syntax (interface) must parse without error nodes (M14)."""
    from tree_sitter import Parser

    from codingdude.jslang import language_for

    src = b'interface P { id: number }\nconst f = (x: number): number => x;\n'
    tree = Parser(language_for('.ts')).parse(src)
    assert not tree.root_node.has_error


def test_l5_rewind_drops_later_checkpoints(home, tmp_path):
    """Rewind removes the undone later checkpoints but keeps the safety one (L5)."""
    from codingdude.checkpoints import CheckpointStore

    store = CheckpointStore(home)
    f = tmp_path / 'doc.txt'
    cp1 = store.begin('s1')
    f.write_text('1\n')
    store.capture_file('s1', cp1, tmp_path, f)
    cp2 = store.begin('s1')
    f.write_text('2\n')
    store.capture_file('s1', cp2, tmp_path, f)

    result = store.rewind_to('s1', cp1, tmp_path)
    ids = [c['id'] for c in store.list_checkpoints('s1')]
    assert cp2 not in ids
    assert result['safety_checkpoint'] in ids
    assert f.read_text() == '1\n'


def test_l8_yaml_frontmatter_skill(home):
    """`---` frontmatter (key: value + [list]) is parsed (L8)."""
    from codingdude.skills import SkillRegistry

    d = home / 'skills' / 'yamlskill'
    d.mkdir(parents=True)
    (d / 'SKILL.md').write_text(
        '---\nname: yamlskill\ndescription: YAML frontmatter\n'
        'triggers: [zap, zip]\n---\n\nBODY-TEXT\n'
    )
    reg = SkillRegistry(home)
    by_name = {s['name']: s for s in reg.index()}
    assert by_name['yamlskill']['description'] == 'YAML frontmatter'
    assert reg.load('yamlskill') == 'BODY-TEXT'
    assert [s['name'] for s in reg.matching('zap it')] == ['yamlskill']


def test_l3_scrubbed_env_drops_secrets_keeps_benign(monkeypatch):
    """Secret-looking names are scrubbed; benign ones survive (L3)."""
    from codingdude.tools import scrubbed_env

    monkeypatch.setenv('DEEPSEEK_API_KEY', 'x')
    monkeypatch.setenv('MY_PASSWORD', 'y')
    monkeypatch.setenv('PATH_LIKE_VAR', 'z')
    env = scrubbed_env()
    assert 'DEEPSEEK_API_KEY' not in env
    assert 'MY_PASSWORD' not in env
    assert 'PATH_LIKE_VAR' in env


async def test_m11_read_only_toolsets_are_attached(engine, workdir):
    """The read-only analysis toolsets are actually offered to the model (M11)."""
    from helpers import scripted
    from pydantic_ai.messages import ModelResponse, TextPart

    def capture(messages, info):
        names = sorted(
            t.name for t in (info.model_request_parameters.function_tools or [])
        )
        return ModelResponse(parts=[TextPart(content=','.join(names))])

    outcome = await engine.run(prompt='list tools', workdir=workdir, model=scripted(capture))
    for tool in ('repo_map', 'find_unused_exports', 'ci_status', 'dependency_audit'):
        assert tool in outcome.output, tool


async def test_h7_headless_run_persists_incrementally(engine, workdir):
    """A crash mid-run leaves the partial exchange in the Session (H7)."""
    from pydantic_ai.exceptions import ModelAPIError
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    state = {'n': 0}

    def fn(messages, info):
        state['n'] += 1
        if state['n'] == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name='list_dir', args={'path': '.'})]
            )
        raise ModelAPIError(model_name='crash', message='boom')

    async def stream_fn(messages, info):
        state['n'] += 1
        if state['n'] == 1:
            from pydantic_ai.models.function import DeltaToolCall
            yield {0: DeltaToolCall(name='list_dir', json_args='{"path": "."}')}
            return
        raise ModelAPIError(model_name='crash', message='boom')

    model = FunctionModel(fn, stream_function=stream_fn, model_name='crash')
    crashed = False
    try:
        await engine.run(prompt='do it', workdir=workdir, model=model)
    except Exception:  # noqa: BLE001 — any failure is fine; we assert on persistence
        crashed = True
    assert crashed, 'the crashing run must not report success'
    sessions = engine._db.list_sessions(workdir)
    assert sessions
    assert engine._db.load_messages(sessions[0].session_id)


async def test_m11_ci_tool_degrades_without_gh(monkeypatch, workdir):
    """A missing `gh` must return a message, not raise WinError 2 (M11)."""
    import asyncio

    from codingdude import tools

    async def boom(*args, **kwargs):
        raise FileNotFoundError(2, 'The system cannot find the file specified')

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', boom)
    ci_status = tools.build_ci_toolset(workdir).tools['ci_status'].function
    assert 'gh is not installed' in await ci_status()


async def test_m11_audit_tool_degrades_without_binary(monkeypatch, workdir):
    """A missing audit binary must return a message, not raise (M11)."""
    import asyncio

    from codingdude import tools

    async def boom(*args, **kwargs):
        raise FileNotFoundError(2, 'The system cannot find the file specified')

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', boom)
    (workdir / 'pyproject.toml').write_text('[project]\nname = "x"\nversion = "0"\n')
    audit = tools.build_audit_toolset(workdir).tools['dependency_audit'].function
    assert 'not installed' in (await audit()).lower()
