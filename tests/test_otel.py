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
"""R100: reading the local OTel store through the running viewer.

The store is never opened here (see `codingdude.otel`): DuckDB is single-writer
and the viewer owns the file, so every read is a JSON-RPC call to the viewer
that already holds it. #362: that rule is pinned at the end of this file — a
docstring cannot fail CI, so the read path is executed under a watcher that
records any attempt to import duckdb.
"""
import ast
import importlib
import importlib.util
import socket
import sys
import types
from pathlib import Path

import pytest

from codingdude import otel

# --- the injection boundary -------------------------------------------------


@pytest.mark.parametrize('bad', [
    '',
    '   ',
    "s' OR 1=1 --",
    's; DROP TABLE spans',
    'a b',
    'x' * 65,
    '../etc/passwd',
    'sess\ndelete',
])
def test_a_session_id_that_could_reach_sql_is_rejected(bad):
    """The viewer's query method takes raw SQL: no binding, no escape hatch.

    So the id is validated, and junk is refused rather than quoted — an escaped
    value could still name the wrong conversation.
    """
    with pytest.raises(ValueError):
        otel.valid_session_id(bad)


@pytest.mark.parametrize('good', ['xkySeYy1wKU', 'abc_-9', 'A' * 64])
def test_a_server_minted_session_id_is_accepted(good):
    assert otel.valid_session_id(good) == good


# --- precision --------------------------------------------------------------


def test_nanoseconds_become_iso_without_touching_float_precision():
    """A live value from the store. 1.79e18 ns exceeds JS's 2^53, so the
    conversion must happen here: the browser would round it to the nearest
    256ns and silently misplace every span."""
    assert otel._ns_to_iso(1795001109831587200) == '2026-11-18T11:25:09.831587+00:00'
    assert otel._ns_to_iso(0) == '1970-01-01T00:00:00+00:00'
    assert otel._ns_to_iso(None) is None


def test_the_span_payload_carries_no_raw_nanoseconds(monkeypatch):
    """duration_s is a float in seconds; a raw int would round in JS."""
    monkeypatch.setattr(otel, '_rpc', lambda *a, **k: {
        'columns': [
            {'name': 'trace_id', 'type': 'VARCHAR'},
            {'name': 'name', 'type': 'VARCHAR'},
            {'name': 'start_time', 'type': 'UBIGINT'},
            {'name': 'duration_ns', 'type': 'UBIGINT'},
            {'name': 'status_code', 'type': 'TINYINT'},
        ],
        'rows': [['t1', 'chat m', 1795001109831587200, 4209298200, 0]],
        'truncated': False,
    })
    [span] = otel.session_spans('sess1')['spans']
    assert span['start_time'] == '2026-11-18T11:25:09.831587+00:00'
    assert span['duration_s'] == 4.209
    assert span['status'] == 'unset'


# --- the projection ---------------------------------------------------------


def test_the_query_never_selects_the_prompt_bodies(monkeypatch):
    """`gen_ai.input.messages`/`output.messages`/`system_instructions` hold the
    full prompt and repository code (70-113KB per model call). Shipping those
    to a browser panel would make it unusable — tokens and cost answer "what
    happened" without spraying code around the UI."""
    seen: dict = {}

    def fake_rpc(method, params, **kwargs):
        seen.update(method=method, params=params)
        return {'columns': [], 'rows': [], 'truncated': False}

    monkeypatch.setattr(otel, '_rpc', fake_rpc)
    otel.session_spans('sess1')
    assert seen['method'] == 'query'
    sql = seen['params']['sql']
    assert "resource.attributes['codingdude.session_id'] = 'sess1'" in sql
    for heavy in (
        'gen_ai.input.messages', 'gen_ai.output.messages', 'gen_ai.system_instructions',
    ):
        assert heavy not in sql


@pytest.mark.parametrize(('given', 'expected'), [(0, 1), (-5, 1), (10_000, 500), (7, 7)])
def test_the_limit_is_clamped_before_it_reaches_the_viewer(given, expected):
    assert otel._clamp(given) == expected


# --- failure is a value, not an exception at the boundary -------------------


def test_a_json_rpc_error_becomes_a_readable_failure(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                'jsonrpc': '2.0', 'id': 1,
                'error': {'message': 'Binder Error: no such column'},
            }

    monkeypatch.setattr(otel.httpx, 'post', lambda *a, **k: Response())
    with pytest.raises(otel.ViewerUnavailable, match='Binder Error'):
        otel.query('SELECT 1')


def test_a_missing_viewer_is_reported_not_raised():
    """Port 9 (discard) is not served: the probe must answer, not explode."""
    ok, error = otel.viewer_reachable('http://127.0.0.1:9')
    assert ok is False
    assert '/rpc' in error


def test_the_collector_probe_sees_a_listening_port():
    """Tracing with no collector is a silent no-op (BatchSpanProcessor drops on
    its own thread), so the dot must be able to tell the truth both ways."""
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert otel.collector_reachable(f'http://127.0.0.1:{port}') is True
    finally:
        server.close()
    assert otel.collector_reachable(f'http://127.0.0.1:{port}') is False


@pytest.mark.parametrize('bad', ['', 'not-a-url', 'http://127.0.0.1', 'ftp://x:1'])
def test_an_unusable_endpoint_is_not_reachable(bad):
    assert otel.collector_reachable(bad) is False


# --- endpoints --------------------------------------------------------------


def test_the_status_endpoint_reports_each_leg_separately(tmp_path, monkeypatch):
    """Three answers, because each fails differently: the config default, the
    collector port, and the query API."""
    from test_lane import _test_app

    monkeypatch.setattr(otel, 'collector_reachable', lambda *a, **k: True)
    monkeypatch.setattr(otel, 'viewer_reachable', lambda *a, **k: (False, 'refused'))
    c, h = _test_app(tmp_path)
    with c:
        body = c.get('/telemetry/status', headers=h).json()
    assert body['collector_reachable'] is True
    assert body['viewer_reachable'] is False
    assert body['viewer_error'] == 'refused'
    assert body['config_enabled'] is False
    assert body['viewer_endpoint'].startswith('http://')


def test_a_missing_viewer_degrades_the_panel_instead_of_500ing(tmp_path, monkeypatch):
    """A viewer that is not running is a state, not a CodingDude bug."""
    from test_lane import _test_app

    def boom(*args, **kwargs):
        raise otel.ViewerUnavailable('connection refused')

    monkeypatch.setattr(otel, 'session_spans', boom)
    c, h = _test_app(tmp_path)
    with c:
        response = c.get('/sessions/sess1/otel/spans', headers=h)
    assert response.status_code == 200
    body = response.json()
    assert body['reachable'] is False
    assert 'connection refused' in body['error']
    assert body['spans'] == []


def test_a_session_id_that_could_reach_sql_is_a_400(tmp_path):
    from test_lane import _test_app

    c, h = _test_app(tmp_path)
    with c:
        response = c.get(f'/sessions/{"a" * 65}/otel/spans', headers=h)
    assert response.status_code == 400


def test_the_spans_endpoint_returns_what_the_module_found(tmp_path, monkeypatch):
    from test_lane import _test_app

    monkeypatch.setattr(
        otel, 'session_spans',
        lambda sid, **k: {'spans': [{'name': 'chat m', 'trace_id': 't1'}],
                          'truncated': False},
    )
    c, h = _test_app(tmp_path)
    with c:
        body = c.get('/sessions/sess1/otel/spans', headers=h).json()
    assert body['reachable'] is True
    assert body['error'] is None
    assert body['spans'] == [{'name': 'chat m', 'trace_id': 't1'}]


# --- the switch rides the same rail as yolo ---------------------------------


def _app_with_fake_popen(tmp_path, monkeypatch):
    from test_lane import _test_app

    monkeypatch.setenv('CODEDUDE_HOME', str(tmp_path / 'home'))
    cmds: list = []

    def fake_popen(cmd, **kwargs):
        cmds.append(cmd)

        class Worker:
            pid = 4242

            def poll(self):
                return None

            def terminate(self):
                return None

        return Worker()

    # Patch the server module's reference, never the shared subprocess module.
    monkeypatch.setattr(
        'codingdude.server.subprocess', types.SimpleNamespace(Popen=fake_popen))
    return _test_app(tmp_path), cmds


def test_the_toggle_reaches_the_worker_argv(tmp_path, monkeypatch):
    (c, h), cmds = _app_with_fake_popen(tmp_path, monkeypatch)
    with c:
        wd = tmp_path / 'proj'
        wd.mkdir()
        sid = c.post('/sessions', json={'workdir': str(wd)}, headers=h).json()[
            'session_id']

        c.post(f'/sessions/{sid}/runs', json={'prompt': 'x', 'telemetry': True},
               headers=h)
        assert '--telemetry' in cmds[-1]

        c.post(f'/sessions/{sid}/runs', json={'prompt': 'x', 'telemetry': False},
               headers=h)
        assert '--no-telemetry' in cmds[-1]
        assert '--telemetry' not in cmds[-1]

        c.post(f'/sessions/{sid}/runs', json={'prompt': 'x'}, headers=h)
        assert '--telemetry' not in cmds[-1]
        assert '--no-telemetry' not in cmds[-1]


def test_the_worker_flag_is_tri_state(monkeypatch):
    """Absent must mean "no opinion" — otherwise the config default could never
    apply, and the toggle would silently become the only switch."""
    import logging

    from codingdude import worker

    captured: list = []

    def fake_run(args):
        captured.append(args)

        async def noop():
            return 0

        return noop()

    class SilentHandler(logging.NullHandler):
        """FileHandler stand-in: accepts the (path, encoding=...) call, writes
        nothing. NullHandler, not a duck-typed stub — main() attaches whatever
        this is to the ROOT logger, so a fake without `level` breaks every
        later logging call in the session."""

        def __init__(self, *args, **kwargs):
            super().__init__()

    root = logging.getLogger()
    before = list(root.handlers)
    monkeypatch.setattr(worker, 'run', fake_run)
    # main() mirrors logs into ~/.codingdude/logs; keep the test off the disk.
    monkeypatch.setattr(worker.logging, 'FileHandler', SilentHandler)
    try:
        assert worker.main(['--session', 's']) == 0
        assert captured[-1].telemetry is None
        assert worker.main(['--session', 's', '--telemetry']) == 0
        assert captured[-1].telemetry is True
        assert worker.main(['--session', 's', '--no-telemetry']) == 0
        assert captured[-1].telemetry is False
    finally:
        # monkeypatch restores the NAME; the handler instance it installed on
        # the root logger would outlive the test and poison every later one.
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)


# --- the rule, enforced (#362) ----------------------------------------------
#
# `codingdude.otel`'s docstring says the read path never opens the store. Prose
# does not fail CI: nothing stopped the next edit from adding `import duckdb`
# and taking the single-writer lock the viewer already holds — and because
# duckdb is *not* a dependency of this project (the viewer owns it), a direct
# `duckdb.connect` would fail in a way that looks like a missing package rather
# than a broken invariant. So the rule is executed, not just written down.


class _ForbiddenModule(types.ModuleType):
    """Stands in for duckdb: the import itself succeeds (so the attempt is
    recorded rather than dying in the importer), but touching it fails loudly."""

    def __getattr__(self, name):
        # The import machinery probes dunders (``__path__``, ``__all__``) while
        # initialising the module handle — those must behave normally or the
        # stub breaks the import instead of recording it.
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        raise AssertionError(
            f'codingdude.otel reached duckdb.{name} — the store belongs to the '
            'viewer that holds it open; read it over JSON-RPC instead'
        )


class _StubLoader:
    def __init__(self, module):
        self.module = module

    def create_module(self, spec):
        return self.module

    def exec_module(self, module):
        return None


class _DuckDBWatcher:
    """Meta-path finder that answers `import duckdb` with a stub and remembers
    that someone asked."""

    def __init__(self):
        self.attempts: list[str] = []
        self._stub = _ForbiddenModule('duckdb')

    def find_spec(self, name, path=None, target=None):
        if name != 'duckdb' and not name.startswith('duckdb.'):
            return None
        self.attempts.append(name)
        return importlib.util.spec_from_loader(name, _StubLoader(self._stub))


def _span_payload():
    return {
        'columns': [
            {'name': 'trace_id', 'type': 'VARCHAR'},
            {'name': 'name', 'type': 'VARCHAR'},
            {'name': 'start_time', 'type': 'UBIGINT'},
            {'name': 'duration_ns', 'type': 'UBIGINT'},
            {'name': 'status_code', 'type': 'TINYINT'},
        ],
        'rows': [['t1', 'chat m', 1795001109831587200, 4209298200, 0]],
        'truncated': False,
    }


def test_the_module_never_names_duckdb_in_an_import():
    """#362, static half. A *top-level* `import duckdb` runs before any test can
    install a watcher, so the runtime check below cannot see it: with duckdb
    absent the suite dies at collection with a puzzling "No module named
    'duckdb'", and with duckdb installed it would sail straight through. So the
    source is parsed — any import statement naming duckdb fails here, wherever
    in the module it sits."""
    tree = ast.parse(Path(otel.__file__).read_text(encoding='utf-8'))
    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            named.add(node.module.split('.')[0])
    assert 'duckdb' not in named


def test_the_read_path_never_imports_duckdb(monkeypatch):
    """#362: reload the module under the watcher and run a real read.

    A reload re-executes the module body, so a `import duckdb` added at the top
    is caught here; running `session_spans` catches one added inside the query
    path (that import would also resolve to the stub, whose first attribute
    access raises)."""
    watcher = _DuckDBWatcher()
    sys.meta_path.insert(0, watcher)
    try:
        module = importlib.reload(otel)
        monkeypatch.setattr(module, '_rpc', lambda *a, **k: _span_payload())
        assert module.session_spans('sess1')['spans'][0]['name'] == 'chat m'
    finally:
        sys.meta_path.remove(watcher)
        sys.modules.pop('duckdb', None)  # the stub must not outlive the test
    assert watcher.attempts == []


def test_the_watcher_fires_on_a_direct_import():
    """The negative control, without which the assertion above could pass for
    the trivial reason that the watcher never sees anything."""
    watcher = _DuckDBWatcher()
    sys.meta_path.insert(0, watcher)
    try:
        importlib.import_module('duckdb')
    finally:
        sys.meta_path.remove(watcher)
        sys.modules.pop('duckdb', None)
    assert watcher.attempts == ['duckdb']

