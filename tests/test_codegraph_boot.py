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
"""R19/#33: codegraph boot is evented and self-describing.

Before this ticket a failed `codegraph init` was completely silent — the
run started with broken navigation tools and the agent blind-retried,
burning tokens. Now boot returns a status dict, the engine emits a
CODEGRAPH_BOOT trace event, and a failure injects a one-line hint into the
instructions so the model skips straight to grep instead of retrying.
"""

import json
from types import SimpleNamespace

from codingdude.codegraph_boot import boot_codegraph, boot_hint


def _runner(returncode=0, stdout='indexed'):
    def runner(cmd, cwd, timeout=None):
        return SimpleNamespace(returncode=returncode, stdout=stdout)
    return runner


# --- boot_codegraph status ---------------------------------------------------

def test_boot_ok_when_index_created(tmp_path):
    status = boot_codegraph(tmp_path, runner=_runner(), cli_path='/fake')
    assert status == {'status': 'ok', 'reason': None}


def test_boot_skipped_when_index_present(tmp_path):
    (tmp_path / '.codegraph').mkdir()
    (tmp_path / '.codegraph' / 'db').write_text('x')
    calls = []
    status = boot_codegraph(
        tmp_path, runner=lambda cmd, cwd, timeout=None: calls.append(cmd),
        cli_path='/fake',
    )
    assert status == {'status': 'skipped', 'reason': None}
    assert calls == []


def test_boot_reinits_partial_index(tmp_path):
    # Health check: an empty/corrupt .codegraph dir must not count as indexed.
    (tmp_path / '.codegraph').mkdir()
    status = boot_codegraph(tmp_path, runner=_runner(), cli_path='/fake')
    assert status == {'status': 'ok', 'reason': None}


def test_boot_failed_without_cli(tmp_path, monkeypatch):
    import codingdude.codegraph_boot as boot_mod
    monkeypatch.setattr(boot_mod, 'find_codegraph_cli', lambda: None)
    status = boot_codegraph(tmp_path, runner=_runner(), cli_path=None)
    assert status['status'] == 'failed'
    assert status['reason'] == 'codegraph CLI not found'


def test_boot_failed_on_nonzero_exit(tmp_path):
    status = boot_codegraph(tmp_path, runner=_runner(returncode=1), cli_path='/fake')
    assert status['status'] == 'failed'
    assert 'exit 1' in status['reason']


def test_boot_failed_on_timeout(tmp_path):
    def runner(cmd, cwd, timeout=None):
        raise TimeoutError()
    status = boot_codegraph(tmp_path, runner=runner, cli_path='/fake')
    assert status['status'] == 'failed'
    assert 'timed out' in status['reason']


def test_boot_failed_on_error(tmp_path):
    def boom(cmd, cwd, timeout=None):
        raise RuntimeError('cli exploded')
    status = boot_codegraph(tmp_path, runner=boom, cli_path='/fake')
    assert status['status'] == 'failed'
    assert 'cli exploded' in status['reason']


# --- prompt hint -------------------------------------------------------------

def test_hint_only_on_failure(tmp_path):
    assert boot_hint({'status': 'failed', 'reason': 'exit 1'})
    assert boot_hint({'status': 'ok', 'reason': None}) is None
    assert boot_hint({'status': 'skipped', 'reason': None}) is None


# --- engine seam: event + instruction hint -----------------------------------

async def test_run_emits_codegraph_boot_event(engine, workdir):
    events = []
    outcome = await engine.run(
        prompt='boot check', workdir=workdir,
        model=__import__('helpers').scripted(__import__('helpers').say('done')),
        emit=events.append, trace=False,
    )
    assert outcome.output == 'done'
    boots = [e for e in events if e.get('type') == 'CODEGRAPH_BOOT']
    assert len(boots) == 1
    assert boots[0]['status'] in {'ok', 'skipped', 'failed'}


async def test_run_injects_hint_into_instructions_on_failure(engine, workdir, monkeypatch):
    import codingdude.codegraph_boot as boot_mod

    captured: dict = {}

    real = boot_mod.boot_codegraph

    def fake_boot(workdir, **kwargs):
        status = real(workdir, **kwargs)
        status.update(status='failed', reason='codegraph CLI not found')
        return status

    monkeypatch.setattr(boot_mod, 'boot_codegraph', fake_boot)

    import helpers
    from pydantic_ai.messages import ModelResponse, TextPart

    def fn(messages, info):
        text = info and json.dumps(getattr(info, 'instructions', None) or '')
        text = text or ''
        for m in messages:
            for p in getattr(m, 'parts', []):
                text += str(getattr(p, 'content', ''))
        captured['seen'] = 'codegraph' in text and 'unavailable' in text
        return ModelResponse(parts=[TextPart(content='ok')])

    outcome = await engine.run(prompt='hint check', workdir=workdir, model=helpers.scripted(fn))
    assert outcome.output == 'ok'
    assert captured['seen'] is True


# --- #203: stale-index self-heal --------------------------------------------

def test_index_is_stale_when_source_newer(tmp_path):
    import os
    import time

    from codingdude.codegraph_boot import index_is_stale

    (tmp_path / ".codegraph").mkdir()
    (tmp_path / ".codegraph" / "index.bin").write_bytes(b"x")
    (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
    now = time.time()
    os.utime(tmp_path / ".codegraph" / "index.bin", (now - 100, now - 100))
    os.utime(tmp_path / "app.py", (now, now))
    assert index_is_stale(tmp_path) is True


def test_index_fresh_when_no_newer_sources(tmp_path):
    import os
    import time

    from codingdude.codegraph_boot import index_is_stale

    (tmp_path / ".codegraph").mkdir()
    idx = tmp_path / ".codegraph" / "index.bin"
    idx.write_bytes(b"x")
    (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
    now = time.time()
    os.utime(tmp_path / "app.py", (now - 100, now - 100))
    os.utime(idx, (now, now))
    assert index_is_stale(tmp_path) is False


def test_index_staleness_ignores_skipped_dirs(tmp_path):
    import os
    import time

    from codingdude.codegraph_boot import index_is_stale

    (tmp_path / ".codegraph").mkdir()
    idx = tmp_path / ".codegraph" / "index.bin"
    idx.write_bytes(b"x")
    junk = tmp_path / "node_modules" / "dep.js"
    junk.parent.mkdir()
    junk.write_text("x", encoding="utf-8")
    now = time.time()
    os.utime(idx, (now - 100, now - 100))
    os.utime(junk, (now, now))
    assert index_is_stale(tmp_path) is False


def test_boot_refreshes_stale_index(tmp_path):
    import os
    import time

    from codingdude.codegraph_boot import boot_codegraph

    (tmp_path / ".codegraph").mkdir()
    idx = tmp_path / ".codegraph" / "index.bin"
    idx.write_bytes(b"x")
    (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
    now = time.time()
    os.utime(idx, (now - 100, now - 100))
    os.utime(tmp_path / "app.py", (now, now))
    status = boot_codegraph(tmp_path, runner=_runner(), cli_path="/fake")
    assert status["status"] == "ok"
    assert "stale" in status["reason"]


def test_boot_skips_when_index_fresh(tmp_path):
    import os
    import time

    from codingdude.codegraph_boot import boot_codegraph

    (tmp_path / ".codegraph").mkdir()
    idx = tmp_path / ".codegraph" / "index.bin"
    idx.write_bytes(b"x")
    (tmp_path / "app.py").write_text("x = 1", encoding="utf-8")
    now = time.time()
    os.utime(tmp_path / "app.py", (now - 100, now - 100))
    os.utime(idx, (now, now))
    status = boot_codegraph(tmp_path, runner=_runner(), cli_path="/fake")
    assert status == {"status": "skipped", "reason": None}

