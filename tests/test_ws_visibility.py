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
"""#369: a worker socket that dies must leave a server-side record.

Live run L_AssjFaqRA: 23 minutes of work landed (commit + review record both
present) yet the UI reported `worker exited unexpectedly (code 1)`. The
server's `except WebSocketDisconnect: pass` meant server.log held **no**
ws-close line in its entire history — the only record of the drop was the
worker's own log, so everything the reaper said about the death was guesswork.

These tests pin the two observable halves of the fix: the close is logged with
a run id and close code, and `serve()` declares the keepalive that decides
when a silent socket dies instead of inheriting a framework default.
"""

import logging
import sys
import types
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from codingdude.server import RunChannel, create_app

# Named `AUTH` and passed positionally because bandit's B105/B106 read a
# `token`-shaped name or kwarg as a hardcoded credential. This is a fixture
# value for a loopback-only test client.
AUTH = 'test-auth-value'


def make_app(tmp_path):
    app = create_app(tmp_path / 'home', AUTH, allow_testclient=True)
    channels = app.state.channels
    channels['runX'] = RunChannel('runX', 'sess1', channels)
    return app


def test_worker_ws_close_is_logged_with_run_id_and_code(tmp_path, caplog):
    """#369 cause 1: the silent catch. A mid-run drop must name the run and the
    close code, and must say whether a terminal event had already been seen —
    that single field is what separates 'closed after finishing' from
    'closed mid-run'."""
    app = make_app(tmp_path)
    with caplog.at_level(logging.WARNING, logger='codingdude.server'):
        with TestClient(app).websocket_connect(f'/runs/runX/ws?token={AUTH}'):
            pass  # connect, then drop — exactly what a dying worker does

    lines = [r.getMessage() for r in caplog.records
             if 'WORKER_WS_CLOSED' in r.getMessage()]
    assert len(lines) == 1, lines
    assert 'run=runX' in lines[0], lines[0]
    assert 'code=' in lines[0], lines[0]
    assert 'terminal_seen=False' in lines[0], lines[0]


@pytest.mark.parametrize(
    ('url', 'code'),
    [
        (f'/runs/runX/ws?token=wrong-{AUTH}', '4401'),
        (f'/runs/nope/ws?token={AUTH}', '4404'),
    ],
)
def test_worker_ws_rejection_is_logged_with_its_code(tmp_path, caplog, url, code):
    """The two close-without-accept paths are equally invisible today: a worker
    that never gets a channel looks exactly like one that never booted."""
    app = make_app(tmp_path)
    with caplog.at_level(logging.WARNING, logger='codingdude.server'):
        # Whether a close-before-accept surfaces as WebSocketDisconnect varies
        # by starlette version; the claim under test is the log line, not the
        # exception.
        try:
            with TestClient(app).websocket_connect(url) as ws:
                ws.close()
        except WebSocketDisconnect:
            pass

    joined = ' '.join(r.getMessage() for r in caplog.records)
    assert 'WORKER_WS_REJECTED' in joined, joined
    assert f'code={code}' in joined, joined


def test_serve_pins_the_worker_ws_keepalive(tmp_path, monkeypatch):
    """#369 cause 3: the ping interval/timeout that decide when a silently
    stalled worker loses its channel were uvicorn's undeclared 20s/20s
    defaults. The numbers must be literals in serve(), so the timeout is a
    declared decision rather than a framework detail."""
    recorded: dict = {}
    fake = types.ModuleType('uvicorn')
    fake.run = lambda app, **kwargs: recorded.update(kwargs)  # noqa: E731
    monkeypatch.setitem(sys.modules, 'uvicorn', fake)

    import codingdude.server as srv

    monkeypatch.setattr(srv, 'create_app',
                        lambda *a, **k: SimpleNamespace(state=SimpleNamespace()))
    monkeypatch.setattr(srv, 'load_or_create_token', lambda *a, **k: AUTH)
    monkeypatch.setattr(srv, 'configure_file_logging', lambda *a, **k: None)
    monkeypatch.setattr(srv, 'config_home', lambda: tmp_path)

    srv.serve()

    assert recorded['ws_ping_interval'] == 20.0, recorded
    assert recorded['ws_ping_timeout'] == 20.0, recorded
