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
"""R10 tracer: per-run cost/latency telemetry (tests/test_telemetry.py)."""

import pytest

from codingdude.config import Config, ModelLineup, ShellConfig, load_config
from codingdude.telemetry import estimate_cost, run_usage_event

PRICING = {
    'deepseek-v4-pro': {'input': 0.27, 'output': 1.1},
    'glm': {'input': 0.5, 'output': 2.0},
}


def test_estimate_cost_exact_and_substring():
    assert estimate_cost(PRICING, 'deepseek-v4-pro', 1_000_000, 1_000_000) == pytest.approx(1.37)
    assert estimate_cost(PRICING, 'zai:glm-5.3', 2_000_000, 1_000_000) == pytest.approx(3.0)


def test_estimate_cost_unpriced_is_none():
    assert estimate_cost(PRICING, 'unknown-model', 1000, 1000) is None
    assert estimate_cost(None, 'deepseek-v4-pro', 1000, 1000) is None


def test_run_usage_event_prefers_provider_cost():
    event = run_usage_event(
        model_name='deepseek-v4-pro', requests=3,
        input_tokens=1_000_000, output_tokens=1_000_000,
        cost_usd=0.99, duration_s=12.5, pricing=PRICING,
    )
    assert event == {
        'type': 'RUN_USAGE', 'model': 'deepseek-v4-pro', 'requests': 3,
        'input_tokens': 1_000_000, 'output_tokens': 1_000_000,
        'cost_usd': 0.99, 'cost_source': 'provider', 'duration_s': 12.5,
    }


def test_run_usage_event_falls_back_to_pricing_then_unpriced():
    priced = run_usage_event(
        model_name='glm-5.3', requests=1, input_tokens=2_000_000,
        output_tokens=1_000_000, cost_usd=None, duration_s=1.0, pricing=PRICING,
    )
    assert priced['cost_usd'] == pytest.approx(3.0)
    assert priced['cost_source'] == 'pricing'
    unpriced = run_usage_event(
        model_name='mystery', requests=1, input_tokens=10, output_tokens=10,
        cost_usd=None, duration_s=1.0, pricing=PRICING,
    )
    assert unpriced['cost_usd'] is None and unpriced['cost_source'] == 'unpriced'


def test_config_loads_pricing(tmp_path):
    (tmp_path / 'config.toml').write_text(
        '[models]\nmain = "deepseek:deepseek-v4-pro"\n'
        '[models.pricing.deepseek-v4-pro]\ninput = 0.27\noutput = 1.1\n',
        encoding='utf-8',
    )
    config = load_config(tmp_path)
    assert config.models.pricing == {'deepseek-v4-pro': {'input': 0.27, 'output': 1.1}}
    assert Config.defaults().models.pricing is None


def _engine(home, db, pricing=None):
    from codingdude.engine import Engine

    config = Config(
        models=ModelLineup(
            main='deepseek:deepseek-v4-pro',
            subagent='deepseek:deepseek-v4-flash',
            fallback='zai:glm-5.3',
            pricing=pricing,
        ),
        shell=ShellConfig(),
    )
    return Engine(config=config, db=db)


async def test_engine_run_emits_run_usage(home, db, tmp_path):
    from helpers import scripted
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.usage import RunUsage

    model = scripted(lambda messages, info: ModelResponse(
        parts=[TextPart(content='hi')],
        usage=RunUsage(input_tokens=42, output_tokens=7, requests=1),
    ))
    events: list[dict] = []
    outcome = await _engine(home, db, pricing={'scripted': {'input': 1.0, 'output': 2.0}}).run(
        prompt='say hi', workdir=tmp_path, model=model, emit=events.append,
    )
    assert outcome.status == 'complete'
    assert len([e for e in events if e['type'] == 'RUN_USAGE']) == 1
    event = next(e for e in events if e['type'] == 'RUN_USAGE')
    # streamed runs may re-report usage; assert accounting is present and
    # cost derives from the configured rates
    assert event['input_tokens'] >= 1 and event['output_tokens'] >= 1
    assert event['requests'] == 1 and event['duration_s'] >= 0
    assert event['cost_source'] == 'pricing'
    assert event['cost_usd'] == pytest.approx(
        event['input_tokens'] * 1e-6 + event['output_tokens'] * 2e-6
    )
