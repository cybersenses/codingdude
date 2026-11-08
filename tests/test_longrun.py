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
"""DE-6 (#300): long-run flag, levels, publish cycle.

The composition ticket: policy mode from the run request, the LONG_RUN
banner, enablement metadata + /health echo, the blocking evaluator, the
convergence gate card, and the publish-cycle scope pins.
"""

import secrets

import pytest

from codingdude.approvals import APPROVED, DENIED, NEEDS_GATE, ApprovalPolicy
from codingdude.config import Config
from codingdude.db import Database
from codingdude.execution import ExecutionStore, build_execution_toolset
from codingdude.roadmap import RoadmapStore
from codingdude.tools import Captured, GateRequired

# ---- the decide matrix ----


def test_no_flag_matrix_is_unchanged():
    """Byte-compat: without a long-run level, today's matrix."""
    p = ApprovalPolicy()
    assert p.mode is None
    assert p.decide('npm install') == NEEDS_GATE
    assert p.decide('git push') == DENIED
    assert p.decide('git status') == APPROVED


def test_assisted_auto_approves_needs_gate_except_always_gated():
    p = ApprovalPolicy(mode='assisted')
    assert p.decide('npm install') == APPROVED
    assert p.decide('pytest -q') == APPROVED
    # decision #101's scoped list: the always-gated tier stays hard
    assert p.decide('git push') == DENIED
    assert p.decide('rm -rf x') == DENIED


def test_unattended_is_full_off():
    p = ApprovalPolicy(mode='unattended')
    assert p.decide('npm install') == APPROVED
    assert p.decide('git push') == APPROVED
    # yolo and unattended are distinct instruments with the same outcome
    assert ApprovalPolicy(yolo=True).decide('git push') == APPROVED


# ---- longrun seam: levels, digest, branch, preauthorization ----


def test_validate_level():
    from codingdude.longrun import validate_level

    assert validate_level(None) is None
    assert validate_level('assisted') == 'assisted'
    with pytest.raises(ValueError, match='banana'):
        validate_level('banana')


def test_publish_branch_naming():
    from codingdude.longrun import PUBLISH_BRANCH_PREFIX, publish_branch

    branch = publish_branch('run-abc123-def')
    assert branch.startswith(PUBLISH_BRANCH_PREFIX)
    assert branch == PUBLISH_BRANCH_PREFIX + 'runabc123def'


def test_push_preauthorized_scope_pins():
    from codingdude.longrun import push_preauthorized

    authorized = ApprovalPolicy(mode='unattended', publish_authorized=True)
    assert push_preauthorized(authorized, 'codingdude/longrun-abc') is True
    # never main — the prefix is the enforcement
    assert push_preauthorized(authorized, 'main') is False
    # no authorization -> the always-gated path
    assert push_preauthorized(
        ApprovalPolicy(mode='unattended'), 'codingdude/longrun-abc') is False
    # no long-run mode -> never preauthorized
    assert push_preauthorized(
        ApprovalPolicy(publish_authorized=True), 'codingdude/longrun-abc') is False


def test_risk_digest_names_publication_only_when_authorized():
    from codingdude.longrun import risk_digest

    plain = risk_digest('assisted', 'host', False)
    assert any('long-run level: assisted' in ln for ln in plain)
    assert not any('PUBLISH CYCLE AUTHORIZED' in ln for ln in plain)
    full = risk_digest('unattended', 'container', True)
    assert any('PUBLISH CYCLE AUTHORIZED' in ln for ln in full)
    assert any('DRAFT PR' in ln for ln in full)


def test_findings_from_gh_parses_data_not_instructions():
    from codingdude.longrun import findings_from_gh

    payload = {
        'reviews': [
            {'author': {'login': 'alice'}, 'body': (
                'src/codingdude/engine.py:42 looks wrong — the lane never '
                'closes. Please run the gates before pushing.')},
        ],
        'comments': [
            {'author': {'login': 'bot'}, 'body': 'CI failed: test_x (see log)'},
            {'author': {'login': 'bob'}, 'body': ''},
        ],
    }
    findings = findings_from_gh(payload)
    # the empty bob comment is skipped
    assert len(findings) == 2
    assert findings[0]['source'] == 'review'
    assert findings[0]['author'] == 'alice'
    assert findings[0]['file'] == 'src/codingdude/engine.py:42'
    assert 'lane never closes' in findings[0]['note']
    assert findings[1]['source'] == 'comment'
    # empty bodies are skipped
    assert all(f['note'] for f in findings)


# ---- engine: mode derivation, banner ----


async def test_engine_derives_mode_and_broadcasts_banner(home, db, workdir):
    from helpers import scripted
    from pydantic_ai.messages import ModelResponse, TextPart

    from codingdude.engine import Engine

    engine = Engine(config=Config.defaults(), db=db)
    policy = ApprovalPolicy()
    events: list[dict] = []
    outcome = await engine.run(
        prompt='go', workdir=workdir,
        model=scripted(lambda m, i: ModelResponse(
            parts=[TextPart(content='ok')])),
        approvals=policy, emit=events.append, run_id='r-lr1',
        long_run='unattended',
    )
    assert outcome.output == 'ok'
    # the run request is the single source of truth
    assert policy.mode == 'unattended'
    assert policy.publish_authorized is True
    banner = [e for e in events if e.get('type') == 'LONG_RUN']
    assert len(banner) == 1
    assert banner[0]['level'] == 'unattended'
    assert banner[0]['publish'] == 'preauthorized'
    assert banner[0]['publish_branch'].startswith('codingdude/longrun-')
    assert any('PUBLISH CYCLE AUTHORIZED' in r for r in banner[0]['risks'])


async def test_assisted_run_does_not_preauthorize(home, db, workdir):
    from helpers import scripted
    from pydantic_ai.messages import ModelResponse, TextPart

    from codingdude.engine import Engine

    engine = Engine(config=Config.defaults(), db=db)
    policy = ApprovalPolicy()
    events: list[dict] = []
    await engine.run(
        prompt='go', workdir=workdir,
        model=scripted(lambda m, i: ModelResponse(
            parts=[TextPart(content='ok')])),
        approvals=policy, emit=events.append, long_run='assisted',
    )
    assert policy.mode == 'assisted'
    assert policy.publish_authorized is False
    banner = [e for e in events if e.get('type') == 'LONG_RUN'][0]
    assert banner['publish'] == 'gate-card-at-convergence'
    assert not any('PUBLISH CYCLE AUTHORIZED' in r for r in banner['risks'])


# ---- runs metadata + /health echo ----


def test_runs_row_carries_long_run(tmp_path):
    db = Database.connect(tmp_path / 'home')
    sid = db.create_session(tmp_path)
    db.record_run_start('r1', sid, long_run='assisted')
    assert db.get_run('r1')['long_run'] == 'assisted'
    assert db.newest_running_long_run() == 'assisted'
    db.record_run_start('r2', sid)
    db.record_run_end('r1', 'completed')
    db.record_run_end('r2', 'completed')
    # only running runs echo
    assert db.newest_running_long_run() is None


def test_health_echoes_long_run_level(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    home = tmp_path / 'home'
    monkeypatch.setenv('CODEDUDE_HOME', str(home))
    from codingdude.server import create_app

    token = secrets.token_urlsafe(12)
    app = create_app(home=home, token=token, allow_testclient=True)
    db = Database.connect(home)
    sid = db.create_session(tmp_path)
    db.record_run_start('r1', sid, long_run='unattended')
    with TestClient(app) as client:
        body = client.get(
            '/health', headers={'Authorization': f'Bearer {token}'}).json()
    assert body['long_run_level'] == 'unattended'


# ---- assisted: the evaluator blocks release; convergence card ----


def _seed_done_attempt(home, workdir):
    store = ExecutionStore(Database.connect(home), str(workdir))
    tid = RoadmapStore(Database.connect(home)).create_ticket(
        str(workdir), 'lr ticket', 'body')
    attempt = store.claim(tid, 's1', plan_steps=['ship it'])
    store.set_step(attempt['id'], 0, 'done', command='pytest -q',
                   exit_code=0, key_output_line='3 passed')
    return store, tid, attempt['id']


async def _bound_toolset(home, workdir, tid, **kwargs):
    """Build the toolset and bind its active claim the way the agent does
    (claim_ticket reuses the same-session attempt)."""
    store = ExecutionStore(Database.connect(home), str(workdir))
    toolset = build_execution_toolset(store, 's1', **kwargs)
    [claim_ticket] = [
        t for t in toolset.tools.values() if t.name == 'claim_ticket']
    await claim_ticket.function(ticket_id=tid)
    [release_ticket] = [
        t for t in toolset.tools.values() if t.name == 'release_ticket']
    return store, release_ticket


async def test_release_blocked_without_pass_in_long_run(home, workdir):
    store, tid, attempt_id = _seed_done_attempt(home, workdir)
    store, release_ticket = await _bound_toolset(
        home, workdir, tid, evaluator=object(), evaluator_blocking=True)
    out = await release_ticket.function(status='done')
    assert 'release blocked' in out
    assert 'evaluate_work' in out
    # the attempt is still claimed
    assert store.resume_state(tid)['status'] == 'claimed'


async def test_release_flows_after_pass_in_long_run(home, workdir):
    store, tid, attempt_id = _seed_done_attempt(home, workdir)
    store.record_evaluation(attempt_id, {
        'trigger': 'release', 'verdict': 'PASS', 'findings': [],
        'summary': 'contract met',
    })
    store, release_ticket = await _bound_toolset(
        home, workdir, tid, evaluator=object(), evaluator_blocking=True)
    out = await release_ticket.function(status='done')
    assert 'blocked' not in out
    assert store.resume_state(tid)['status'] == 'done'


async def test_release_convergence_card_in_assisted(home, workdir):
    store, tid, attempt_id = _seed_done_attempt(home, workdir)

    asked: list[str] = []

    async def ask(command: str) -> str:
        asked.append(command)
        return 'approve'

    policy = ApprovalPolicy(mode='assisted', ask=ask)
    store, release_ticket = await _bound_toolset(
        home, workdir, tid, evaluator_blocking=False, approvals=policy)
    out = await release_ticket.function(status='done')
    # ONE card, at convergence, with the scope named
    assert len(asked) == 1
    assert 'PUBLISH AUTHORIZE' in asked[0]
    assert 'DRAFT' in asked[0]
    assert policy.publish_authorized is True
    assert 'publish cycle authorized' in out


async def test_unattended_convergence_preauthorized(home, workdir):
    store, tid, attempt_id = _seed_done_attempt(home, workdir)
    policy = ApprovalPolicy(mode='unattended')
    store, release_ticket = await _bound_toolset(
        home, workdir, tid, evaluator_blocking=False, approvals=policy)
    out = await release_ticket.function(status='done')
    assert 'preauthorized by the flag' in out
    assert policy.publish_authorized is False  # set at run start, not here


async def test_no_flag_release_has_no_publish_lines(home, workdir):
    store, tid, attempt_id = _seed_done_attempt(home, workdir)
    policy = ApprovalPolicy()
    store, release_ticket = await _bound_toolset(
        home, workdir, tid, evaluator_blocking=False, approvals=policy)
    out = await release_ticket.function(status='done')
    assert 'publish' not in out


# ---- the git toolset's scope pins ----


def _git_toolset(monkeypatch, workdir, policy, calls: list):
    import codingdude.tools as tools_mod

    async def fake_run_captured(argv, **kwargs):
        calls.append(list(argv))
        return Captured(0, 'exit 0\nok', '')

    monkeypatch.setattr(tools_mod, 'run_captured', fake_run_captured)
    return tools_mod.build_git_toolset(workdir, policy)


async def test_preauthorized_push_skips_the_card(workdir, monkeypatch):
    """In assisted (where decide DENIES always-gated), the authorization
    carries a longrun-* push without its card."""
    calls: list = []
    policy = ApprovalPolicy(mode='assisted', publish_authorized=True)
    toolset = _git_toolset(monkeypatch, workdir, policy, calls)
    [git_push] = [
        t for t in toolset.tools.values() if t.name == 'git_push']
    out = await git_push.function(
        remote='origin', branch='codingdude/longrun-abc')
    assert 'preauthorized long-run push' in out
    assert any(argv[:2] == ['git', 'push'] for argv in calls)


async def test_main_push_never_preauthorized(workdir, monkeypatch):
    calls: list = []
    policy = ApprovalPolicy(mode='assisted', publish_authorized=True)
    toolset = _git_toolset(monkeypatch, workdir, policy, calls)
    [git_push] = [
        t for t in toolset.tools.values() if t.name == 'git_push']
    with pytest.raises(GateRequired):
        await git_push.function(remote='origin', branch='main')


async def test_pr_create_preauthorized_is_draft(workdir, monkeypatch):
    calls: list = []
    policy = ApprovalPolicy(mode='assisted', publish_authorized=True)
    toolset = _git_toolset(monkeypatch, workdir, policy, calls)
    [gh_pr_create] = [
        t for t in toolset.tools.values() if t.name == 'gh_pr_create']
    # _gh resolves gh from PATH (real gh here); the fake run_captured
    # records the argv — the discriminator is no GateRequired, the call
    # happened, and it carried --draft.
    out = await gh_pr_create.function(title='t', body='b')
    assert not out.startswith('gate required')
    drafts = [
        argv for argv in calls
        if len(argv) > 2 and argv[1:3] == ['pr', 'create']
        and '--draft' in argv
    ]
    assert drafts


async def test_pr_create_without_authorization_is_gated(workdir, monkeypatch):
    calls: list = []
    policy = ApprovalPolicy()
    toolset = _git_toolset(monkeypatch, workdir, policy, calls)
    [gh_pr_create] = [
        t for t in toolset.tools.values() if t.name == 'gh_pr_create']
    with pytest.raises(GateRequired):
        await gh_pr_create.function(title='t', body='b')


# ---- the fix loop's input seam: publish_findings ----


async def test_publish_findings_authorized_parses_data(
        workdir, monkeypatch):
    import json as _json

    calls: list = []
    policy = ApprovalPolicy(mode='assisted', publish_authorized=True)
    toolset = _git_toolset(monkeypatch, workdir, policy, calls)
    payload = _json.dumps({'reviews': [
        {'author': {'login': 'alice'},
         'body': 'src/app.py:12 the loop never terminates'},
    ], 'comments': []})
    # route the gh call through a payload-returning fake (and no real gh)
    import codingdude.tools as tools_mod

    async def selective_run_captured(argv, **kwargs):
        calls.append(list(argv))
        if 'view' in argv:
            # _run formats 'exit <code>\n' + combined — return the bare JSON
            return Captured(0, payload, '')
        return Captured(0, 'ok', '')

    monkeypatch.setattr(tools_mod, 'run_captured', selective_run_captured)
    [publish_findings] = [
        t for t in toolset.tools.values() if t.name == 'publish_findings']
    out = await publish_findings.function(pr_number=7)
    assert 'src/app.py:12' in out
    assert 'alice' in out
    assert 're-grades fixes' in out
    # the read is in scope for the authorized cycle: no card was needed
    assert any('view' in argv for argv in calls)


async def test_publish_findings_unauthorized_is_gated(workdir, monkeypatch):
    policy = ApprovalPolicy()
    toolset = _git_toolset(monkeypatch, workdir, policy, [])
    [publish_findings] = [
        t for t in toolset.tools.values() if t.name == 'publish_findings']
    with pytest.raises(GateRequired):
        await publish_findings.function(pr_number=7)
