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

import sys
from pathlib import Path
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


def test_a_malformed_endpoint_in_config_raises_at_load(tmp_path):
    (tmp_path / 'config.toml').write_text(
        '[telemetry]\notlp_endpoint = "4318"\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'\[telemetry\]'):
        load_config(tmp_path)


# --- adoption guard --------------------------------------------------------


def test_every_agent_construction_is_named():
    """A span must be able to say *which* agent spent the tokens.

    Same shape as the capabilities guard in test_agent_caps: scanning the
    source is the only check that stays true for agents nobody has written yet.
    """
    import ast

    missing = []
    for path in sorted(Path('src/codingdude').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, 'id', None) != 'Agent':
                continue
            keywords = {k.arg for k in node.keywords if k.arg}
            if 'name' not in keywords:
                missing.append(f'{path.name}:{node.lineno}')
    assert missing == [], (
        'Agent(...) without name= — spans would be unattributable: '
        + ', '.join(missing)
    )
