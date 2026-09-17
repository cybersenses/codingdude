"""Engine seam: the scripted model drives real read-only tools on a temp Workdir."""

import os
import sys
from pathlib import Path

import pytest
from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


def tool_then_answer(tool_name: str, tool_args: dict, answer_check):
    """Scripted model: call a tool on turn 1, answer from the tool result on turn 2."""

    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[ToolCallPart(tool_name=tool_name, args=tool_args)]
            )
        returns = [
            p.content
            for m in messages
            for p in m.parts
            if isinstance(p, (ToolReturnPart, RetryPromptPart))
        ]
        return ModelResponse(parts=[TextPart(content=answer_check(returns))])

    return scripted(fn)


async def test_read_file_tool(engine, workdir):
    outcome = await engine.run(
        prompt='read the app',
        workdir=workdir,
        model=tool_then_answer(
            'read_file',
            {'path': 'src/app.py'},
            lambda returns: (
                'found greet' if any('greet' in str(r) for r in returns) else 'missing'
            ),
        ),
    )
    assert outcome.output == 'found greet'


async def test_grep_tool_finds_content(engine, workdir):
    outcome = await engine.run(
        prompt='where is greet?',
        workdir=workdir,
        model=tool_then_answer(
            'grep',
            {'pattern': 'greet'},
            lambda returns: (
                'in app.py' if any('app.py' in str(r) for r in returns) else 'missing'
            ),
        ),
    )
    assert outcome.output == 'in app.py'


async def test_list_dir_and_glob_tools(engine, workdir):
    for tool_name, args, marker in [
        ('list_dir', {'path': '.'}, 'README.md'),
        ('glob', {'pattern': 'src/*.py'}, 'app.py'),
    ]:
        outcome = await engine.run(
            prompt=f'list via {tool_name}',
            workdir=workdir,
            model=tool_then_answer(
                tool_name,
                args,
                lambda returns, marker=marker: (
                    'saw files' if any(marker in str(r) for r in returns) else 'missing'
                ),
            ),
        )
        assert outcome.output == 'saw files', tool_name


async def test_outside_workdir_is_refused_not_crashing(engine, workdir):
    def answer(returns):
        if any('outside' in str(r).lower() for r in returns):
            return 'refused it'
        return 'no refusal seen'

    outcome = await engine.run(
        prompt='read the secret',
        workdir=workdir,
        model=tool_then_answer(
            'read_file', {'path': '../secret.txt'}, answer
        ),
    )
    assert outcome.output == 'refused it'


async def test_list_dir_and_grep_missing_path_are_graceful(home, workdir):
    from codingdude.tools import build_toolset

    toolset = build_toolset(workdir, read_only=True)
    listing = toolset.tools['list_dir'].function(path='nope')
    assert 'not found' in listing.lower()
    matches = toolset.tools['grep'].function(pattern='x', path='nope')
    assert 'not found' in matches.lower()


async def test_shell_masks_workdir_self_reference(home, workdir):
    """`cd <own workdir>` must not read as an outside path (spurious gate)."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.tools import build_shell_toolset

    workdir.mkdir(parents=True, exist_ok=True)
    policy = ApprovalPolicy()
    toolset = build_shell_toolset(workdir, policy)
    shell = toolset.tools['shell'].function

    # Read-only command that mentions the workdir by every path spelling.
    cmd = (
        f'echo "project at {workdir} and {workdir.as_posix()}"; '
        'git log --oneline | head -3'
    )
    out = await shell(cmd)
    assert 'exit code' in out  # ran without a gate


async def test_shell_still_gates_true_outside_paths(home, workdir):
    from codingdude.approvals import ApprovalPolicy

    workdir.mkdir(parents=True, exist_ok=True)
    other = workdir.parent / 'elsewhere'
    cmd = f'cat {other.as_posix()}/secret.txt'
    # Workdir masking must not hide paths outside the project.
    decision = ApprovalPolicy().decide(cmd)
    assert decision != 'approved'


async def test_shell_capture_hook_registers_new_renders(home, workdir):
    """A command that creates an image auto-registers it as a render (R1)."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.tools import build_shell_toolset

    workdir.mkdir(parents=True, exist_ok=True)
    captured = []
    toolset = build_shell_toolset(
        workdir, ApprovalPolicy(yolo=True), on_render=captured.append,
    )
    shell = toolset.tools['shell'].function
    script = (
        "import pathlib; p = pathlib.Path('shot.png'); p.write_bytes(b'x'); "
        "pathlib.Path('ignored.txt').write_text('x')"
    )
    py = sys.executable.replace('\\', '/')
    out = await shell(f'"{py}" -c "{script}"')
    assert 'exit code: 0' in out
    assert 'shot.png' in captured
    assert 'ignored.txt' not in captured


# --- R12: deterministic file-edit pipeline -------------------------------

def _tool(workdir, name, **kwargs):
    from codingdude.tools import build_toolset

    return build_toolset(workdir, **kwargs).tools[name].function


def test_edit_refuses_non_utf8(tmp_path):
    """Non-UTF-8 bytes must never be silently corrupted (R12 #1)."""
    target = tmp_path / 'blob.py'
    target.write_bytes(b'hello \xff\xfe world')
    edit = _tool(tmp_path, 'edit_file')
    import pytest
    from pydantic_ai import ModelRetry

    with pytest.raises(ModelRetry, match='UTF-8'):
        edit('blob.py', 'hello', 'goodbye')
    assert target.read_bytes() == b'hello \xff\xfe world'  # untouched


def test_edit_preserves_line_endings(tmp_path):
    """LF stays LF, CRLF stays CRLF; \n-style old_text matches CRLF files (R12 #2)."""
    lf = tmp_path / 'lf.py'
    lf.write_bytes(b'a = 1\nb = 2\n')
    _tool(tmp_path, 'edit_file')('lf.py', 'b = 2', 'b = 3')
    assert b'\r' not in lf.read_bytes()

    crlf = tmp_path / 'crlf.py'
    crlf.write_bytes(b'a = 1\r\nb = 2\r\n')
    _tool(tmp_path, 'edit_file')('crlf.py', 'b = 2', 'b = 3')  # \n old_text
    assert crlf.read_bytes() == b'a = 1\r\nb = 3\r\n'


def test_read_file_reports_bytes_verbatim(tmp_path):
    """read_file must not normalize newlines (observation == bytes on disk)."""
    crlf = tmp_path / 'crlf.py'
    crlf.write_bytes(b'a = 1\r\nb = 2\r\n')
    out = _tool(tmp_path, 'read_file')('crlf.py')
    assert '\r\n' in out


def test_edit_refuses_stale_file(tmp_path):
    """An external change since last observation must abort the edit (R12 #3)."""
    import pytest
    from pydantic_ai import ModelRetry

    f = tmp_path / 'x.py'
    f.write_bytes(b'a = 1\n')
    from codingdude.tools import build_toolset

    ts = build_toolset(tmp_path)
    ts.tools['read_file'].function('x.py')  # observe
    f.write_bytes(b'a = 999\n')  # external writer
    with pytest.raises(ModelRetry, match='changed since'):
        ts.tools['edit_file'].function('x.py', 'a = 1', 'a = 2')
    assert f.read_bytes() == b'a = 999\n'  # external change intact


def test_edit_verifies_and_rolls_back(tmp_path, monkeypatch):
    """If the written file diverges from intent, original bytes are restored."""
    import pytest
    from pydantic_ai import ModelRetry

    from codingdude import tools

    f = tmp_path / 'x.py'
    f.write_bytes(b'a = 1\n')
    monkeypatch.setattr(tools, '_atomic_write', lambda t, text: t.write_text('GARBAGE'))
    with pytest.raises(ModelRetry, match='verification failed'):
        _tool(tmp_path, 'edit_file')('x.py', 'a = 1', 'a = 2')
    assert f.read_bytes() == b'a = 1\n'  # rolled back


def test_write_file_atomic_and_lf_preserved(tmp_path):
    """write_file creates parents, is atomic, and preserves given endings."""
    w = _tool(tmp_path, 'write_file')
    assert w('deep/dir/new.py', 'x = 1\ny = 2\n') == 'wrote deep/dir/new.py'
    data = (tmp_path / 'deep' / 'dir' / 'new.py').read_bytes()
    assert data == b'x = 1\ny = 2\n'
    assert not list(tmp_path.rglob('*.codingdude-tmp'))  # no temp litter


def test_atomic_write_concurrent_no_collision(tmp_path):
    """Two processes writing the same target must never collide on the tmp
    path (WinError 32) — regression for the deterministic `.codingdude-tmp`
    name (R24 #38)."""
    import multiprocessing as mp

    import test_tools as self_mod

    target = tmp_path / 'shared.py'
    target.write_text('seed\n')
    q: mp.Queue = mp.Queue()
    procs = [mp.Process(target=self_mod._atomic_write_worker, args=(str(target), s, q))
             for s in range(2)]
    for p in procs:
        p.start()
    errs = q.get() + q.get()
    for p in procs:
        p.join()
    assert errs == []
    assert not list(tmp_path.glob('*.codingdude-tmp*'))  # no temp litter


def _atomic_write_worker(target_str: str, seed: int, q) -> None:  # spawned on Windows
    from codingdude.tools import _atomic_write

    errs = []
    for i in range(50):
        try:
            _atomic_write(Path(target_str), f'w{seed} round {i}\n')
        except OSError as exc:
            errs.append(f'{type(exc).__name__}: {exc}')
    q.put(errs)


def test_atomic_write_retries_locked_target(tmp_path, monkeypatch):
    """Transient PermissionError on os.replace (AV/editor lock) is retried,
    not fatal (R24 #38)."""
    import os as _os

    import codingdude.tools as tools_mod

    target = tmp_path / 'x.py'
    target.write_text('old\n')
    calls = {'n': 0}
    real_replace = _os.replace

    def flaky(src, dst):
        calls['n'] += 1
        if calls['n'] < 3:
            raise PermissionError(32, 'The process cannot access the file')
        real_replace(src, dst)

    monkeypatch.setattr(_os, 'replace', flaky)
    tools_mod._atomic_write(target, 'new\n')
    assert calls['n'] == 3
    assert target.read_text() == 'new\n'
    assert not list(tmp_path.glob('*.codingdude-tmp*'))  # no temp litter


def test_stale_guard_cleared_by_reread(tmp_path):
    """Re-reading the externally changed file re-arms the guard and edits proceed."""
    f = tmp_path / 'x.py'
    f.write_bytes(b'a = 1\n')
    edit = _tool(tmp_path, 'edit_file')
    read = _tool(tmp_path, 'read_file')
    read('x.py')
    f.write_bytes(b'a = 999\n')
    read('x.py')  # observe the change
    assert edit('x.py', 'a = 999', 'a = 1000') == 'edited x.py'


@pytest.mark.skipif(os.name != 'nt', reason='Windows bash resolution')
def test_shell_argv_windows_resolves_git_bash_not_wsl_stub():
    """Bare `bash` on Windows can resolve to the WSL stub (no distro ->
    UTF-16 'no installed distributions' garbage). We must ship git's own
    bash.exe, or at worst a non-System32 bash."""
    from codingdude.tools import shell_argv

    argv = shell_argv('echo hi')
    assert argv[1] == '-c' and argv[2] == 'echo hi'
    exe = argv[0].lower()
    assert 'system32' not in exe, f'WSL stub selected: {argv[0]}'
    assert exe.endswith('bash.exe') or exe.endswith('bash'), argv[0]
