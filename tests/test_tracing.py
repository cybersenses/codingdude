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
"""R93-C: local-OTLP tracing — off by default, local-only, never fatal."""

import ast
import sys
from types import SimpleNamespace

import pytest
from helpers import say, scripted

from codingdude.config import (
    Config,
    TelemetryConfig,
    _default_config_toml,
    load_config,
    validate_otlp_endpoint,
)
from codingdude.tracing import configure_tracing, traces_url


class FakeExporter:
    """Stands in for OTLPSpanExporter so no collector (or thread) is needed."""

    def __init__(self, endpoint=None):
        self.endpoint = endpoint

    def export(self, spans):
        return 0

    def force_flush(self, timeout_millis=0):
        return 0

    def shutdown(self, timeout_millis=0):
        return 0


class FakeLogfire:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.configure_calls: list[dict] = []
        self.instrument_calls = 0

    def configure(self, **kwargs):
        if self.fail:
            raise RuntimeError('no collector')
        self.configure_calls.append(kwargs)

    def instrument_pydantic_ai(self):
        self.instrument_calls += 1


@pytest.fixture
def fake_tracing(monkeypatch):
    """A recording logfire + a non-exporting OTLP exporter, tracing reset."""
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    import codingdude.tracing as tracing

    fake = FakeLogfire()
    monkeypatch.setitem(sys.modules, 'logfire', fake)
    monkeypatch.setattr(trace_exporter, 'OTLPSpanExporter', FakeExporter)
    monkeypatch.setattr(tracing, '_configured', False, raising=False)
    monkeypatch.setattr(tracing, '_warned', False, raising=False)
    return fake


def _config(enabled: bool, endpoint: str = 'http://127.0.0.1:4318') -> Config:
    defaults = Config.defaults()
    return Config(
        defaults.models,
        defaults.shell,
        defaults.providers,
        telemetry=TelemetryConfig(
            enabled=enabled, otlp_endpoint=endpoint, service_name='codingdude-test'
        ),
    )


# --- the endpoint seam ------------------------------------------------------


@pytest.mark.parametrize('given', [
    'http://127.0.0.1:4318',
    'http://127.0.0.1:4318/',
    'http://127.0.0.1:4318/v1/traces',
])
def test_traces_url_accepts_every_spelling_of_the_same_endpoint(given):
    assert traces_url(given) == 'http://127.0.0.1:4318/v1/traces'


def test_traces_url_keeps_a_path_prefixed_collector():
    assert traces_url('http://box:4318/otlp/') == 'http://box:4318/otlp/v1/traces'


# --- off by default --------------------------------------------------------


def test_disabled_telemetry_instruments_nothing(fake_tracing):
    assert configure_tracing(_config(enabled=False)) is False
    assert fake_tracing.configure_calls == []
    assert fake_tracing.instrument_calls == 0


def test_production_default_is_off():
    """The shipped default must not export anything: run prompts are code."""
    assert TelemetryConfig().enabled is False


def test_a_config_without_the_section_is_not_an_error(fake_tracing):
    """Defensive: an older Config or a stand-in must read as 'off', not crash."""
    assert configure_tracing(SimpleNamespace()) is False
    assert fake_tracing.configure_calls == []


# --- enabled wires a local OTLP exporter ----------------------------------


def test_enabled_telemetry_exports_only_to_the_local_collector(fake_tracing):
    assert configure_tracing(_config(enabled=True)) is True
    [kwargs] = fake_tracing.configure_calls
    assert kwargs['send_to_logfire'] is False
    assert 'token' not in kwargs
    assert kwargs['service_name'] == 'codingdude-test'
    [processor] = kwargs['additional_span_processors']
    assert type(processor).__name__ == 'BatchSpanProcessor'
    assert fake_tracing.instrument_calls == 1


def test_configuring_twice_does_not_double_instrument(fake_tracing):
    assert configure_tracing(_config(enabled=True)) is True
    assert configure_tracing(_config(enabled=True)) is True
    assert len(fake_tracing.configure_calls) == 1
    assert fake_tracing.instrument_calls == 1


def test_a_broken_logfire_setup_degrades_instead_of_raising(fake_tracing):
    fake_tracing.fail = True
    assert configure_tracing(_config(enabled=True)) is False
    assert fake_tracing.instrument_calls == 0


# --- R100: the per-conversation override and attribution --------------------


def test_a_run_can_force_tracing_on_against_the_config_default(fake_tracing):
    """The chat panel's checkbox is per turn: the config default is a default,
    not a veto — otherwise the switch could only ever turn things off."""
    assert configure_tracing(_config(enabled=False), enabled=True) is True
    assert len(fake_tracing.configure_calls) == 1


def test_a_run_can_force_tracing_off_against_the_config(fake_tracing):
    """The expensive direction: an operator with tracing on must still be able
    to keep one conversation out of the store."""
    assert configure_tracing(_config(enabled=True), enabled=False) is False
    assert fake_tracing.configure_calls == []
    assert fake_tracing.instrument_calls == 0


def test_absent_override_is_the_config_default(fake_tracing):
    assert configure_tracing(_config(enabled=True), enabled=None) is True
    assert configure_tracing(_config(enabled=False), enabled=None) is False


def test_the_conversation_is_stamped_on_the_span_resource(fake_tracing):
    """Without these a span only carries pydantic-ai's own per-run
    `gen_ai.conversation.id`, which no CodingDude surface knows."""
    assert configure_tracing(
        _config(enabled=True), session_id='sess-1', run_id='run-1') is True
    [kwargs] = fake_tracing.configure_calls
    assert kwargs['resource_attributes'] == {
        'codingdude.session_id': 'sess-1',
        'codingdude.run_id': 'run-1',
    }


def test_an_unstamped_run_sends_no_empty_attributes(fake_tracing):
    assert configure_tracing(_config(enabled=True)) is True
    [kwargs] = fake_tracing.configure_calls
    assert kwargs['resource_attributes'] == {}


def test_the_logfire_api_surface_we_call_still_exists():
    """The fakes above prove our wiring; this proves the API we wire *to*.

    A real collector cannot run here, so this pins the contract instead of the
    export: if logfire renames a keyword or drops the pydantic-ai instrument,
    `configure_tracing` starts silently blaming the collector.
    """
    import inspect

    import logfire

    params = inspect.signature(logfire.configure).parameters
    for keyword in (
        'send_to_logfire', 'service_name', 'additional_span_processors',
        # R100: the parameter that ties a span to a conversation.
        'resource_attributes',
    ):
        assert keyword in params
    assert callable(logfire.instrument_pydantic_ai)


# --- config surface --------------------------------------------------------


def test_config_toml_documents_the_telemetry_keys():
    text = _default_config_toml(Config.defaults().models)
    assert '[telemetry]' in text
    assert 'enabled = false' in text
    assert 'otlp_endpoint' in text
    # R100: the query port the in-app panel reads through.
    assert 'viewer_endpoint' in text


def test_load_config_reads_the_viewer_endpoint(tmp_path):
    (tmp_path / 'config.toml').write_text(
        '[telemetry]\nviewer_endpoint = "http://127.0.0.1:9000"\n', encoding='utf-8')
    telemetry = load_config(tmp_path).telemetry
    assert telemetry.viewer_endpoint == 'http://127.0.0.1:9000'


def test_a_bad_viewer_endpoint_degrades_the_panel_not_tracing(tmp_path):
    """Unlike a bad otlp_endpoint, this one must NOT switch recording off: the
    viewer endpoint is a read path, and losing the panel is not losing data."""
    (tmp_path / 'config.toml').write_text(
        '[telemetry]\nenabled = true\nviewer_endpoint = "8000"\n', encoding='utf-8')
    telemetry = load_config(tmp_path).telemetry
    assert telemetry.enabled is True
    assert telemetry.viewer_endpoint == TelemetryConfig().viewer_endpoint


def test_load_config_parses_the_telemetry_surface(tmp_path):
    (tmp_path / 'config.toml').write_text(
        '[telemetry]\n'
        'enabled = true\n'
        'otlp_endpoint = "http://127.0.0.1:6006"\n'
        'service_name = "cd-local"\n',
        encoding='utf-8',
    )
    telemetry = load_config(tmp_path).telemetry
    assert telemetry.enabled is True
    assert telemetry.otlp_endpoint == 'http://127.0.0.1:6006'
    assert telemetry.service_name == 'cd-local'


def test_load_config_defaults_telemetry_off(tmp_path):
    (tmp_path / 'config.toml').write_text('[models]\nmain = "a:b"\n', encoding='utf-8')
    assert load_config(tmp_path).telemetry.enabled is False


@pytest.mark.parametrize('bad', ['', '   ', '127.0.0.1:4318', 'grpc://box:4317'])
def test_a_malformed_endpoint_is_rejected_loudly(bad):
    with pytest.raises(ValueError, match='http'):
        validate_otlp_endpoint(bad, where='test')


@pytest.mark.parametrize('bad', [
    'http://127.0.0.1:abc',   # non-numeric port: urlparse().port raises
    'http://127.0.0.1:99999',  # out of range: same exception, different text
    'http://[::1',             # unparseable IPv6 literal
])
def test_an_endpoint_with_an_unusable_port_is_rejected(bad):
    """The prefix check alone accepted these, and the failure then surfaced
    from `.port` deep in the status probe as a 500 rather than as a config
    error the operator can read."""
    with pytest.raises(ValueError, match='port|host'):
        validate_otlp_endpoint(bad, where='test')


def test_a_malformed_endpoint_disables_tracing_instead_of_failing_boot(tmp_path):
    """#341: tracing is optional telemetry — a typo must not stop the worker."""
    (tmp_path / 'config.toml').write_text(
        '[telemetry]\nenabled = true\notlp_endpoint = "4318"\n', encoding='utf-8')
    telemetry = load_config(tmp_path).telemetry
    assert telemetry.enabled is False
    assert telemetry.otlp_endpoint == TelemetryConfig().otlp_endpoint


def test_a_quoted_false_does_not_enable_tracing(tmp_path):
    """`bool('false')` is True, so a quoted value must never switch tracing on.
    It also must not stop the worker: every malformed [telemetry] value — the
    boolean as much as the endpoint — degrades to off (#341 contract)."""
    (tmp_path / 'config.toml').write_text(
        '[telemetry]\nenabled = "false"\n', encoding='utf-8')
    assert load_config(tmp_path).telemetry.enabled is False


def test_a_quoted_true_is_not_trusted_either(tmp_path):
    (tmp_path / 'config.toml').write_text(
        '[telemetry]\nenabled = "true"\n', encoding='utf-8')
    assert load_config(tmp_path).telemetry.enabled is False


def test_an_empty_service_name_falls_back_to_the_default(tmp_path):
    (tmp_path / 'config.toml').write_text(
        '[telemetry]\nenabled = true\nservice_name = "  "\n', encoding='utf-8')
    assert load_config(tmp_path).telemetry.service_name == TelemetryConfig().service_name


def test_a_configuration_failure_is_reported_once(fake_tracing, caplog):
    """`_configured` stays False on failure so a later fixed call can succeed —
    which means every run would re-warn without the separate guard."""
    import logging

    fake_tracing.fail = True
    with caplog.at_level(logging.WARNING, logger='codingdude.tracing'):
        assert configure_tracing(_config(enabled=True)) is False
        assert configure_tracing(_config(enabled=True)) is False
    assert len([r for r in caplog.records if 'tracing disabled' in r.message]) == 1


# --- adoption guard --------------------------------------------------------


# #361: `configure_tracing` used to be one line inside `worker.run()`, so the
# three other places that execute an agent run - review mode, headless and the
# eval replay - emitted no spans at all. The fix is not that line copied three
# times: only the engine knows the session id a run actually writes to
# (headless and eval runs mint theirs *inside* `_ensure_session`), so the call
# lives at the two engine entry points and every caller inherits it.


def _recording_configure(monkeypatch) -> list[dict]:
    """Capture the arguments the shipped code path passes to tracing."""
    import codingdude.tracing as tracing_module

    seen: list[dict] = []

    def fake_configure(config, **kwargs):
        seen.append(kwargs)
        return True

    monkeypatch.setattr(tracing_module, 'configure_tracing', fake_configure)
    return seen


async def test_a_run_configures_tracing_with_the_session_it_writes_to(
    engine, workdir, monkeypatch,
):
    """The id does not exist before the engine resolves the session, so a
    worker-side call could only ever attribute the runs that already know
    theirs - which is why the other three paths had no spans."""
    seen = _recording_configure(monkeypatch)
    outcome = await engine.run(
        prompt='hi', workdir=workdir, model=scripted(say('done')), run_id='run-7',
    )
    assert len(seen) == 1
    assert seen[0]['session_id'] == outcome.session_id
    assert seen[0]['run_id'] == 'run-7'
    # No override: `[telemetry] enabled` decides. The chat panel's switch is
    # the only thing that forces the choice either way.
    assert seen[0]['enabled'] is None


async def test_a_run_forwards_its_own_telemetry_choice(engine, workdir, monkeypatch):
    """A run that says "do not record me" must reach tracing as a decision."""
    seen = _recording_configure(monkeypatch)
    await engine.run(
        prompt='hi', workdir=workdir, model=scripted(say('done')), telemetry=False,
    )
    assert [call['enabled'] for call in seen] == [False]


async def test_a_review_configures_tracing_with_the_conversation_it_reviews(
    engine, monkeypatch,
):
    """Review mode is a real agent run that spends real money; with nothing
    recording it, a reader of the panel would conclude no review ever ran."""
    from codingdude.engine import Engine

    seen = _recording_configure(monkeypatch)

    async def fake_review_diff(self, session_id):
        return ''

    monkeypatch.setattr(Engine, 'review_diff', fake_review_diff)
    verdict = await engine.review('sess-42')
    assert verdict.startswith('CLEAN')
    # No `enabled` override: the config default decides (the server spawns
    # `--review <sid>` with no telemetry flag).
    assert seen == [{'session_id': 'sess-42'}]


def test_the_worker_forwards_the_telemetry_choice_instead_of_configuring(home):
    """The worker used to configure tracing itself, before an Engine existed.
    It now hands the choice to the engine - and must not drop it on the way
    (the H2 lesson: `--fix-loop` was parsed and never forwarded)."""
    from codingdude.worker import engine_run_kwargs

    def run_kwargs(**overrides):
        args = SimpleNamespace(
            prompt='p', workdir='w', image=None, session='s', fix_loop=False,
            run_id='r', long_run=None,
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return engine_run_kwargs(args, model=None)

    assert run_kwargs(telemetry=True)['telemetry'] is True
    assert run_kwargs(telemetry=False)['telemetry'] is False
    assert run_kwargs()['telemetry'] is None  # no flag = the config decides


async def test_a_replay_does_not_record_its_simulated_run(
    home, workdir, monkeypatch,
):
    """`evals.replay` drives a *scripted* model: its token counts are invented,
    and the store it would write to is read as real spend. The opt-out is
    explicit so the omission is a decision rather than a blind spot."""
    from codingdude.evals import replay

    seen = _recording_configure(monkeypatch)
    scenario = {
        'name': 'sim', 'prompt': 'hi',
        'responses': [{'text': 'hello', 'tool_calls': []}], 'checks': [],
    }
    await replay(scenario, workdir, home)
    assert [call['enabled'] for call in seen] == [False]


def test_tracing_is_configured_at_the_engine_seam_and_nowhere_else():
    """The durable guard: this defect was one call site where four were
    needed. Scanning the source is the only check that also covers entry
    points nobody has written yet."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / 'src' / 'codingdude'
    callers = {
        path.name
        for path in root.glob('*.py')
        if path.name != 'tracing.py'
        and 'configure_tracing(' in path.read_text(encoding='utf-8')
    }
    assert callers == {'engine.py'}, (
        'configure_tracing belongs at the engine entry points only; found: '
        + ', '.join(sorted(callers))
    )


def test_every_agent_construction_is_named():
    """A span must be able to say *which* agent spent the tokens.

    Same shape as the capabilities guard in test_agent_caps: scanning the
    source is the only check that stays true for agents nobody has written yet.
    """
    from helpers import agent_calls_missing

    missing = agent_calls_missing('name')
    assert missing == [], (
        'Agent(...) without name= — spans would be unattributable: '
        + ', '.join(missing)
    )


@pytest.mark.parametrize('source', [
    'Agent(model=m)',                                  # bare
    'pydantic_ai.Agent(model=m)',                      # attribute
    'import pydantic_ai as pai\npai.Agent(model=m)',   # module alias
    'from pydantic_ai import Agent as A\nA(model=m)',  # import alias
])
def test_the_agent_matcher_sees_every_construction_form(source):
    """The guard is only worth its green tick if it matches the forms a real
    call site can take — a bare `func.id == 'Agent'` test misses three of these
    four, which is exactly the drift the guard exists to catch."""
    from helpers import agent_call_nodes

    tree = ast.parse(source)
    [call] = agent_call_nodes(tree)
    assert 'name' not in {k.arg for k in call.keywords}


def test_the_agent_matcher_rejects_a_blank_name():
    from helpers import agent_call_nodes

    [call] = agent_call_nodes(ast.parse("Agent(name='', model=m)"))
    assert {k.arg for k in call.keywords} == {'name', 'model'}  # matched at all


def test_no_agent_is_constructed_with_a_blank_name(tmp_path):
    from helpers import agent_calls_missing

    (tmp_path / 'mod.py').write_text("Agent(name='', model=m)\n", encoding='utf-8')
    assert agent_calls_missing('name', tmp_path) == [f'{tmp_path.as_posix()}/mod.py:1']

# ---- R94-C (#347): the export path, proven on the wire ----------------


def test_a_span_reaches_a_real_otlp_collector():
    """The first end-to-end test of the export path.

    R93 shipped `traces_url` + `OTLPSpanExporter` with every test faking the
    exporter, so nothing proved a span ever left the process. This runs a real
    collector on a loopback port and asserts the span arrives at
    `/v1/traces`.

    Ceiling, stated: this proves *our* wiring (endpoint shape, exporter, span
    processor). It does not prove that logfire instruments pydantic-ai — that
    needs a live model call and is covered by the instrumentation guards above.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from codingdude.tracing import traces_url

    paths: list[str] = []
    bodies: list[bytes] = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server requires this name
            length = int(self.headers.get('Content-Length') or 0)
            paths.append(self.path)
            bodies.append(self.rfile.read(length))
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-protobuf')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):  # keep pytest output clean
            return

    server = HTTPServer(('127.0.0.1', 0), Collector)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = TracerProvider()
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=traces_url(f'http://127.0.0.1:{port}'))
            )
        )
        with provider.get_tracer('codingdude').start_as_current_span(
            'delegate.coder'
        ):
            pass
        provider.force_flush(timeout_millis=5000)
        provider.shutdown()
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert paths == ['/v1/traces'], f'wrong path: {paths}'
    assert bodies, 'no span payload reached the collector'
    # OTLP/HTTP carries protobuf; string fields appear verbatim in the bytes.
    assert b'delegate.coder' in bodies[0]
