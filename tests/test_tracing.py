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


def test_the_logfire_api_surface_we_call_still_exists():
    """The fakes above prove our wiring; this proves the API we wire *to*.

    A real collector cannot run here, so this pins the contract instead of the
    export: if logfire renames a keyword or drops the pydantic-ai instrument,
    `configure_tracing` starts silently blaming the collector.
    """
    import inspect

    import logfire

    params = inspect.signature(logfire.configure).parameters
    for keyword in ('send_to_logfire', 'service_name', 'additional_span_processors'):
        assert keyword in params
    assert callable(logfire.instrument_pydantic_ai)


# --- config surface --------------------------------------------------------


def test_config_toml_documents_the_telemetry_keys():
    text = _default_config_toml(Config.defaults().models)
    assert '[telemetry]' in text
    assert 'enabled = false' in text
    assert 'otlp_endpoint' in text


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


async def test_the_worker_enables_tracing_before_it_builds_the_engine(
    home, monkeypatch,
):
    """Tracing is only worth configuring if the process that executes runs turns
    it on. Nothing else pins the call site, so deleting it would leave the whole
    suite green. Ordering is the contract: configure first, then run."""
    from types import SimpleNamespace

    import codingdude.engine as engine_module
    import codingdude.tracing as tracing_module
    import codingdude.worker as worker

    calls: list[str] = []

    def fake_configure(config):
        calls.append('configure')
        return True

    class Stop(Exception):
        pass

    def fake_engine(**kwargs):
        calls.append('engine')
        raise Stop

    monkeypatch.setattr(tracing_module, 'configure_tracing', fake_configure)
    monkeypatch.setattr(engine_module, 'Engine', fake_engine)
    args = SimpleNamespace(workdir=None, budget=None, model=None)
    with pytest.raises(Stop):
        await worker.run(args)
    assert calls == ['configure', 'engine']


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
