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
"""R80-5 #297 (DE-3 remainder): the long-run sandbox lane.

Seams: LongRunLane.create (tier selection + sandbox creation via the shared
create_sandbox core), lane routing through exec_in_sandbox_dir (shell +
fix-loop test command), the LANE trace event (banner + tier line), and the
long_run request-field validation.
"""

from pathlib import Path

import pytest
from helpers import scripted
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


def _git(workdir: Path, *args: str) -> str:
    import shutil
    import subprocess  # nosec B404 - test fixture spawns git only, argv list

    git = shutil.which('git') or 'git'
    result = subprocess.run(
        [git, *args], cwd=workdir, capture_output=True, text=True,
    )  # nosec B603 - test fixture, fixed argv list, no shell
    return result.stdout.strip()


def _init_repo(workdir: Path) -> None:
    _git(workdir, 'init', '-q')
    _git(workdir, '-c', 'user.email=t@t', '-c', 'user.name=t',
         'commit', '-q', '--allow-empty', '-m', 'init')


def shell_then_report(command: str):
    """Model that issues one shell call, then reports what the result carried
    (so tests assert on model-visible truth, not internal return values)."""
    def fn(messages, info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[ToolCallPart(tool_name='shell', args={'command': command})]
            )
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        joined = ' | '.join(returns)
        verdict = (
            'container-tier' if 'tier=container' in joined
            else 'worktree-tier' if 'tier=worktree' in joined
            else 'no-tier-line'
        )
        probe = 'lane-probe-ran' if 'lane-probe' in joined else 'no-probe'
        return ModelResponse(parts=[TextPart(content=f'{verdict} {probe}')])

    return scripted(fn)


# --- unit: tier selection, naming, degraded reasons, event dict


async def test_lane_container_when_docker_usable(workdir, monkeypatch):
    from codingdude import sandbox
    from codingdude.lane import LongRunLane

    monkeypatch.setattr(sandbox, 'docker_usable', lambda: True)
    created = {}

    async def fake_run(argv, cwd, timeout):
        created['argv'] = argv
        return f'exit 0\n{argv[-1]}'

    monkeypatch.setattr(sandbox, '_run', fake_run)
    _init_repo(workdir)
    lane = await LongRunLane.create(workdir, 'abc123def', policy=None)
    assert lane.tier == 'container'
    assert lane.sandbox_ready is True
    assert lane.name == 'longrun-abc123def'
    # #292 contracts ride the shared core: loopback-only publish, worktree mount
    assert any('127.0.0.1:' in a for a in created['argv'])
    event = lane.event
    assert event['type'] == 'LANE'
    assert event['tier'] == 'container'
    assert event['degraded'] is False


async def test_lane_degrades_when_docker_absent(workdir, monkeypatch):
    from codingdude import sandbox
    from codingdude.lane import LongRunLane

    monkeypatch.setattr(sandbox, 'docker_usable', lambda: False)
    lane = await LongRunLane.create(workdir, 'abc123def', policy=None)
    assert lane.tier == 'host'
    assert lane.sandbox_ready is False
    assert lane.reason  # honest: says why the tier degraded
    assert lane.event['degraded'] is True
    assert lane.event['tier'] == 'host'


async def test_lane_bootstraps_commitless_workdir_to_container(
        workdir, monkeypatch):
    """#306: the lane engages the container tier on a commitless workdir.
    Scratch-project bootstrap tasks START with no repo — before the seed
    commit they degraded to the host tier, so the one mode that exists to
    make the first commit could never reach the container. The seed state
    is committed on the base repo; the run's worktree branches from it."""
    from codingdude import sandbox
    from codingdude.lane import LongRunLane

    (workdir / 'seed.py').write_text('print("seed")\n', encoding='utf-8')
    monkeypatch.setattr(sandbox, 'docker_usable', lambda: True)

    async def fake_run(argv, cwd, timeout):
        return f'exit 0\n{argv[-1]}'

    monkeypatch.setattr(sandbox, '_run', fake_run)
    lane = await LongRunLane.create(workdir, 'abc123def', policy=None)
    assert lane.tier == 'container'
    assert lane.sandbox_ready is True
    assert lane.event['degraded'] is False
    # the seed state is committed on the base repo — HEAD exists now
    assert _git(workdir, 'rev-parse', 'HEAD')
    # ...and the worktree branched from it
    assert (workdir / '.codingdude-worktrees' / lane.name).exists()


async def test_lane_reuses_worktree_on_resume(workdir, monkeypatch):
    """#305 post-push review: the worker's auto-resume re-creates the SAME
    lane name after attempt 1's timeout. Attempt 1's worktree is its work
    product (cleanup keeps it) — attempt 2 must adopt it and stay on the
    container tier, not degrade to host on 'worktree already exists'."""
    from codingdude import sandbox
    from codingdude.lane import LongRunLane

    _init_repo(workdir)
    monkeypatch.setattr(sandbox, 'docker_usable', lambda: True)

    async def fake_run(argv, cwd, timeout):
        return f'exit 0\n{argv[-1]}'

    monkeypatch.setattr(sandbox, '_run', fake_run)
    lane1 = await LongRunLane.create(workdir, 'abc123def', policy=None)
    assert lane1.tier == 'container'
    wtree = workdir / '.codingdude-worktrees' / lane1.name
    (wtree / 'product.txt').write_text('attempt-1 work', encoding='utf-8')
    await lane1.cleanup()  # container removed, worktree kept (by design)

    lane2 = await LongRunLane.create(workdir, 'abc123def', policy=None)
    assert lane2.tier == 'container', lane2.reason
    assert lane2.sandbox_ready is True
    # attempt 1's work product survives into the resumed lane
    assert (wtree / 'product.txt').read_text(encoding='utf-8') == 'attempt-1 work'
    await lane2.cleanup()


async def test_lane_degrades_when_bootstrap_fails(workdir, monkeypatch):
    """#306: a bootstrap failure degrades honestly to the host tier with the
    reason in the LANE event — never raises, never silently hosts."""
    import codingdude.lane as lane_mod
    from codingdude import sandbox
    from codingdude.lane import LongRunLane

    monkeypatch.setattr(sandbox, 'docker_usable', lambda: True)
    monkeypatch.setattr(
        lane_mod, 'ensure_commit_ready',
        lambda wd: 'git commit failed: simulated')
    lane = await LongRunLane.create(workdir, 'abc123def', policy=None)
    assert lane.tier == 'host'
    assert lane.sandbox_ready is False
    assert 'bootstrap failed' in (lane.reason or '')
    assert 'git commit failed: simulated' in (lane.reason or '')


async def test_lane_cleanup_removes_container_keeps_worktree(workdir, monkeypatch):
    """The worktree/branch is the run's work product — only the idle container
    is removed at run end (best-effort, never raises)."""
    from codingdude import sandbox
    from codingdude.lane import LongRunLane

    monkeypatch.setattr(sandbox, 'docker_usable', lambda: True)

    async def fake_run(argv, cwd, timeout):
        return f'exit 0\n{argv[-1]}'

    monkeypatch.setattr(sandbox, '_run', fake_run)
    _init_repo(workdir)
    lane = await LongRunLane.create(workdir, 'abc123def', policy=None)
    removals = []

    def fake_run_sync(argv, **kwargs):
        removals.append(argv)

        class R:
            returncode = 0
            stdout = ''
            stderr = ''

        return R()

    monkeypatch.setattr(sandbox.subprocess, 'run', fake_run_sync)
    await lane.cleanup()
    assert any('rm' in a for a in removals), removals
    assert (workdir / '.codingdude-worktrees' / lane.name).exists()


def test_lane_run_routes_through_shared_core(workdir, monkeypatch):
    """sandbox_ready lanes execute via exec_in_sandbox_dir — the R17 core —
    so gating, tier labeling, and container exec cannot drift per-caller."""
    import asyncio

    from codingdude.lane import LongRunLane

    seen = {}

    async def fake_exec(workdir, name, command, policy=None):
        seen['name'], seen['command'], seen['policy'] = name, command, policy
        return 'exit 0\nran-in-sandbox'

    # lane.py binds exec_in_sandbox_dir at import: patch its binding, not
    # sandbox's (the production import is static by design — no indirection).
    monkeypatch.setattr('codingdude.lane.exec_in_sandbox_dir', fake_exec)
    lane = LongRunLane(
        workdir=workdir, name='longrun-x', tier='container',
        sandbox_ready=True, reason=None, policy='fake-policy',
    )
    out = asyncio.run(lane.run('echo hi'))
    assert out == 'exit 0\nran-in-sandbox'
    assert seen == {
        'name': 'longrun-x', 'command': 'echo hi', 'policy': 'fake-policy',
    }


def test_exit_code_of_parses_core_summary():
    from codingdude.lane import exit_code_of

    assert exit_code_of('exit 0\nall green') == 0
    assert exit_code_of('exit 1\n2 failed') == 1
    assert exit_code_of('exit -1\n command timed out after 300s') == -1
    assert exit_code_of('garbage') is None


def _test_app(tmp_path):
    """create_app on a TestClient (monkeypatched Popen keeps the worker
    spawn local); returns (client, headers)."""
    from fastapi.testclient import TestClient

    from codingdude.server import create_app

    tok = 'lane-' + 'test-token'  # noqa: B105 - local server test token
    app = create_app(home=tmp_path / 'home', token=tok, allow_testclient=True)
    app.state.port = 8000
    c = TestClient(app)
    return c, {'Authorization': 'Bearer ' + app.state.token}


# --- engine integration: lane lifecycle + shell routing


async def test_engine_container_lane_routes_shell(home, workdir, monkeypatch):
    """long_run set + Docker usable: sandbox auto-created, shell results carry
    the container tier line, LANE event traced."""
    from codingdude import sandbox
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    _init_repo(workdir)
    monkeypatch.setattr(sandbox, 'docker_usable', lambda: True)

    async def fake_run(argv, cwd, timeout):
        return f'exit 0\n{argv[-1]}'

    monkeypatch.setattr(sandbox, '_run', fake_run)

    async def fake_running(container):
        return True

    monkeypatch.setattr(sandbox, 'container_running', fake_running)

    engine = Engine(config=load_config(), db=Database.connect(home))
    events = []
    outcome = await engine.run(
        prompt='run one command',
        workdir=workdir,
        model=shell_then_report('echo lane-probe'),
        approvals=ApprovalPolicy(yolo=True),
        long_run='assisted',
        emit=events.append,
    )
    assert outcome.status == 'complete'
    assert 'container-tier lane-probe-ran' in outcome.output
    lane_events = [e for e in events if e.get('type') == 'LANE']
    assert lane_events and lane_events[0]['tier'] == 'container'
    assert lane_events[0]['degraded'] is False


async def test_engine_degraded_lane_states_host_tier(home, workdir, monkeypatch):
    """Docker absent: run proceeds on the host tier — LANE event says so
    (never silent), the summary note rides the outcome, shell still works."""
    from codingdude import sandbox
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    _init_repo(workdir)
    monkeypatch.setattr(sandbox, 'docker_usable', lambda: False)

    engine = Engine(config=load_config(), db=Database.connect(home))
    events = []
    outcome = await engine.run(
        prompt='run one command',
        workdir=workdir,
        model=shell_then_report('echo lane-probe'),
        approvals=ApprovalPolicy(yolo=True),
        long_run='unattended',
        emit=events.append,
    )
    assert outcome.status == 'complete'
    assert 'lane-probe-ran' in outcome.output  # shell worked, host-side
    lane_events = [e for e in events if e.get('type') == 'LANE']
    assert lane_events and lane_events[0]['tier'] == 'host'
    assert lane_events[0]['degraded'] is True
    assert outcome.lane_note and 'host' in outcome.lane_note.lower()


async def test_engine_without_long_run_is_byte_for_byte(home, workdir):
    """Contract pin: absent long_run → no LANE event, no lane note, shell
    behaves exactly as today (no tier line in the result)."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    engine = Engine(config=load_config(), db=Database.connect(home))
    events = []
    outcome = await engine.run(
        prompt='run one command',
        workdir=workdir,
        model=shell_then_report('echo lane-probe'),
        approvals=ApprovalPolicy(yolo=True),
        emit=events.append,
    )
    assert outcome.status == 'complete'
    assert not [e for e in events if e.get('type') == 'LANE']
    assert outcome.lane_note is None
    assert 'no-tier-line lane-probe-ran' in outcome.output


async def test_engine_rejects_unknown_long_run_level(home, workdir):
    """Fail fast: an unknown level is a caller error, never a silent default."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine

    engine = Engine(config=load_config(), db=Database.connect(home))
    with pytest.raises(ValueError, match='long_run'):
        await engine.run(
            prompt='x', workdir=workdir,
            model=shell_then_report('echo hi'),
            approvals=ApprovalPolicy(yolo=True),
            long_run='banana',
        )


async def test_engine_fix_loop_routes_tests_through_lane(
        home, workdir, monkeypatch):
    """Fix-until-green test runs are shell work: with a ready lane they
    execute inside the sandbox, not on the host."""
    from codingdude.approvals import ApprovalPolicy
    from codingdude.config import load_config
    from codingdude.db import Database
    from codingdude.engine import Engine
    from codingdude.lane import LongRunLane

    _init_repo(workdir)
    ran_through_lane = []

    class FakeLane:
        tier = 'container'
        sandbox_ready = True
        name = 'longrun-fixloop'
        reason = None

        @property
        def event(self):
            return {'type': 'LANE', 'tier': 'container', 'degraded': False}

        def instructions_block(self):
            return ''

        def summary_note(self):
            return None

        async def run(self, command):
            ran_through_lane.append(command)
            return 'exit 0\n1 passed'

        async def cleanup(self):
            return None

    async def fake_create(workdir, run_id, policy=None):
        return FakeLane()

    monkeypatch.setattr(LongRunLane, 'create', staticmethod(fake_create))

    engine = Engine(config=load_config(), db=Database.connect(home))
    await engine.run(
        prompt='fix until green',
        workdir=workdir,
        model=scripted(lambda m, i: ModelResponse(parts=[TextPart(content='done')])),
        approvals=ApprovalPolicy(yolo=True),
        fix_loop=True,
        test_command='pytest -q',
        long_run='assisted',
    )
    assert ran_through_lane == ['pytest -q']


# --- request-field validation + worker argv (server/worker seams)


def test_start_run_rejects_unknown_long_run_level(tmp_path, monkeypatch):
    """Fail-fast at request validation: unknown levels are a 422, not a
    silent default to interactive."""
    monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))
    # Patch the server's module reference, NOT subprocess.Popen: the server
    # module holds the real subprocess module, and patching Popen on it is a
    # global mutation that breaks third-party imports mid-test (mcp's
    # `subprocess.Popen[bytes]` annotation).
    import types

    monkeypatch.setattr(
        'codingdude.server.subprocess',
        types.SimpleNamespace(Popen=lambda *a, **k: None),
    )
    c, h = _test_app(tmp_path)
    with c:
        wd = tmp_path / 'proj'
        wd.mkdir()
        sid = c.post(
            '/sessions', json={'workdir': str(wd)}, headers=h,
        ).json()['session_id']
        r = c.post(
            f'/sessions/{sid}/runs',
            json={'prompt': 'x', 'long_run': 'banana'}, headers=h,
        )
        assert r.status_code == 422


def test_start_run_passes_long_run_to_worker(tmp_path, monkeypatch):
    """The validated level rides the worker argv (--long-run); absent flag
    adds nothing — the CLI stays byte-identical for interactive runs."""
    monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))
    cmds = []

    def fake_popen(cmd, **kwargs):
        cmds.append(cmd)

        class W:
            pid = 4242

            def poll(self):
                return None

            def terminate(self):
                return None

        return W()

    # Server's module reference (see the 422 test: never patch the shared
    # subprocess module's Popen).
    import types

    monkeypatch.setattr(
        'codingdude.server.subprocess',
        types.SimpleNamespace(Popen=fake_popen),
    )
    c, h = _test_app(tmp_path)
    with c:
        wd = tmp_path / 'proj'
        wd.mkdir()
        sid = c.post(
            '/sessions', json={'workdir': str(wd)}, headers=h,
        ).json()['session_id']
        c.post(
            f'/sessions/{sid}/runs',
            json={'prompt': 'x', 'long_run': 'assisted'}, headers=h,
        )
        assert cmds and '--long-run' in cmds[-1]
        assert cmds[-1][cmds[-1].index('--long-run') + 1] == 'assisted'
        c.post(f'/sessions/{sid}/runs', json={'prompt': 'x'}, headers=h)
        assert '--long-run' not in cmds[-1]


def test_engine_run_kwargs_forwards_long_run():
    from test_worker import _args

    from codingdude import worker

    kwargs = worker.engine_run_kwargs(_args(long_run='unattended'), model='m')
    assert kwargs['long_run'] == 'unattended'
    assert worker.engine_run_kwargs(_args(), model='m')['long_run'] is None


# --- #306: ensure_commit_ready — the bootstrap seam unit tests


def test_ensure_commit_ready_noop_on_committed_repo(workdir):
    """A repo that already has commits is untouched — no extra commits."""
    from codingdude.lane import ensure_commit_ready

    _init_repo(workdir)
    assert ensure_commit_ready(workdir) is None
    assert _git(workdir, 'rev-list', '--count', 'HEAD') == '1'


def test_ensure_commit_ready_seeds_commitless_repo(workdir):
    """git init'ed but commitless: the current state becomes the seed commit
    with the deterministic bootstrap identity."""
    from codingdude.lane import ensure_commit_ready

    _git(workdir, 'init', '-q')
    (workdir / 'greet.py').write_text('print("hi")\n', encoding='utf-8')
    assert ensure_commit_ready(workdir) is None
    assert _git(workdir, 'rev-list', '--count', 'HEAD') == '1'
    assert 'long-run lane bootstrap' in _git(workdir, 'log', '-1', '--format=%s')
    # the seed file is IN the commit
    assert 'greet.py' in _git(workdir, 'show', '--name-only', '--format=')


def test_ensure_commit_ready_empty_dir_gets_root_commit(workdir):
    """A plain (not-even-git) empty dir: init + empty root commit — enough
    for the worktree to branch from."""
    from codingdude.lane import ensure_commit_ready

    assert ensure_commit_ready(workdir) is None
    assert _git(workdir, 'rev-list', '--count', 'HEAD') == '1'
    assert _git(workdir, 'log', '-1', '--format=%an') == 'codingdude'
