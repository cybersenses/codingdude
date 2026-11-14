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
"""R91 #338: cache capability profiles for every agent.

#337 shipped caching on the main run agent only, as a single hardcoded
boolean. These tests pin the general form: a retention tier, the per-profile
`messages` flag, and provider-specific passthrough that reaches a real Agent's
model settings (not merely a constructed object).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import Caching
from pydantic_ai.models.test import TestModel

from codingdude.agent_caps import (
    CACHE_RETENTIONS,
    DEFAULT_CACHE_RETENTION,
    ONE_SHOT,
    PROVIDER_CACHE_SETTINGS,
    RUN,
    ProviderCacheSettings,
    cache_capabilities,
    parse_cache_retention,
    validate_cache_settings,
)
from codingdude.config import ModelLineup, ModelLineupIn, _default_config_toml, load_config
from codingdude.run_pipeline import context_capabilities, one_shot_capabilities


def _models(prompt_cache=DEFAULT_CACHE_RETENTION, messages=True, settings=None):
    return SimpleNamespace(
        prompt_cache=prompt_cache,
        prompt_cache_messages=messages,
        prompt_cache_settings=settings or {},
    )


# --- the seam: resolution ---------------------------------------------------

@pytest.mark.parametrize('tier', CACHE_RETENTIONS)
def test_retention_tier_is_forwarded(tier):
    (cap,) = cache_capabilities(_models(prompt_cache=tier), RUN)
    assert isinstance(cap, Caching)
    assert cap.retention == tier
    assert cap.messages is True


def test_run_profile_caches_the_conversation():
    (cap,) = cache_capabilities(_models(), RUN)
    assert cap.messages is True, 'the main run re-reads its conversation'


def test_one_shot_profile_caches_only_the_prefix():
    """Grader/reviewer/summariser send a fresh conversation each call — a
    conversation breakpoint there is a 1.25x write nothing ever reads."""
    (cap,) = cache_capabilities(_models(), ONE_SHOT)
    assert cap.messages is False
    assert cap.retention == DEFAULT_CACHE_RETENTION


def test_config_messages_flag_governs_the_run_profile_only():
    (run_cap,) = cache_capabilities(_models(messages=False), RUN)
    assert run_cap.messages is False
    (one_shot,) = cache_capabilities(_models(messages=True), ONE_SHOT)
    assert one_shot.messages is False


def test_disabled_and_unconfigured_yield_no_capabilities():
    assert cache_capabilities(_models(prompt_cache=False), RUN) == []
    assert cache_capabilities(None, RUN) == []


def test_default_retention_outlives_the_ask_timeout():
    """ask_user blocks up to 1800 s (6x Anthropic's 5-minute tier): caching at
    the provider default would expire mid-session and re-write the prefix."""
    assert DEFAULT_CACHE_RETENTION == '1h'


# --- provider passthrough ---------------------------------------------------

def test_provider_settings_ride_as_a_capability():
    caps = cache_capabilities(
        _models(settings={'bedrock_cache_messages': '1h'}), ONE_SHOT
    )
    assert [type(c) for c in caps] == [Caching, ProviderCacheSettings]
    assert caps[1].get_model_settings() == {'bedrock_cache_messages': '1h'}


def test_provider_settings_still_apply_when_unified_flag_is_off():
    """`prompt_cache = false` disables library-managed caching; an explicit
    provider map is a separate opt-in, not the same intent."""
    caps = cache_capabilities(
        _models(prompt_cache=False, settings={'anthropic_cache_messages': '5m'})
    )
    assert [type(c) for c in caps] == [ProviderCacheSettings]


def test_passthrough_reaches_a_real_agent_model_settings():
    """Capability settings merge onto the agent's own; the passthrough key
    rides beside the unified one instead of replacing our plumbing."""
    caps = cache_capabilities(
        _models(prompt_cache='30m', settings={'openai_prompt_cache_retention': '24h'})
    )
    agent = Agent(model=TestModel(), capabilities=caps)
    settings = agent._cap_model_settings
    # A tier with messages=True is pydantic-ai's short form (cache=<tier>).
    assert settings['cache'] == '30m'
    assert settings['openai_prompt_cache_retention'] == '24h'


def test_one_shot_agent_sends_the_explicit_no_conversation_config():
    caps = cache_capabilities(_models(prompt_cache='30m'), ONE_SHOT)
    agent = Agent(model=TestModel(), capabilities=caps)
    assert agent._cap_model_settings['cache'] == {
        'retention': '30m', 'messages': False,
    }


# --- validation at the boundary --------------------------------------------

@pytest.mark.parametrize('value', [True, False, *CACHE_RETENTIONS])
def test_parse_accepts_bool_and_tiers(value):
    assert parse_cache_retention(value) == value


@pytest.mark.parametrize('value', ['1hr', '5', 3, None, ['1h']])
def test_parse_rejects_anything_else(value):
    with pytest.raises(ValueError, match='prompt_cache'):
        parse_cache_retention(value)


def test_unknown_provider_key_is_rejected():
    with pytest.raises(ValueError, match='unknown key'):
        validate_cache_settings({'bedrock_cache_msg': '1h'})


def test_every_documented_provider_key_is_accepted():
    accepted = validate_cache_settings(
        {key: True for key in PROVIDER_CACHE_SETTINGS}
    )
    assert set(accepted) == set(PROVIDER_CACHE_SETTINGS)


def test_empty_and_none_passthrough_are_empty_maps():
    assert validate_cache_settings(None) == {}
    assert validate_cache_settings({}) == {}


# --- config surface --------------------------------------------------------

def test_config_toml_documents_the_new_keys():
    text = _default_config_toml(
        ModelLineup(main='a:b', subagent='a:b', fallback='a:b'))
    assert 'prompt_cache = "1h"' in text
    assert 'prompt_cache_messages' in text
    assert 'prompt_cache_settings' in text


def test_load_config_parses_the_cache_surface(tmp_path):
    (tmp_path / 'config.toml').write_text(
        '[models]\n'
        'prompt_cache = "30m"\n'
        'prompt_cache_messages = false\n'
        '[models.prompt_cache_settings]\n'
        'bedrock_cache_messages = "1h"\n',
        encoding='utf-8',
    )
    models = load_config(tmp_path).models
    assert models.prompt_cache == '30m'
    assert models.prompt_cache_messages is False
    assert models.prompt_cache_settings == {'bedrock_cache_messages': '1h'}


@pytest.mark.parametrize(
    'line', ['prompt_cache = "1hr"\n', 'prompt_cache = 3\n'],
)
def test_load_config_rejects_a_bad_tier_at_load_time(tmp_path, line):
    (tmp_path / 'config.toml').write_text('[models]\n' + line, encoding='utf-8')
    with pytest.raises(ValueError, match='prompt_cache'):
        load_config(tmp_path)


def test_config_boundary_rejects_a_bad_tier_and_key():
    with pytest.raises(ValueError, match='prompt_cache'):
        ModelLineupIn(main='a:b', subagent='a:b', fallback='a:b',
                      prompt_cache='bad')
    with pytest.raises(ValueError, match='unknown key'):
        ModelLineupIn(main='a:b', subagent='a:b', fallback='a:b',
                      prompt_cache_settings={'typo': 1})


def test_config_boundary_defaults_to_an_hour():
    lineup = ModelLineupIn(main='a:b', subagent='a:b', fallback='a:b')
    assert lineup.prompt_cache == '1h'
    assert lineup.prompt_cache_messages is True
    assert lineup.prompt_cache_settings == {}


# --- adoption: the run and its one-shot agents ------------------------------

def test_context_capabilities_adds_the_guard_and_the_run_cache():
    from codingdude.context import ContextManager

    caps = context_capabilities(
        ContextManager(model_limit=100_000), None, models=_models(prompt_cache='1h')
    )
    assert [type(c).__name__ for c in caps] == ['ProcessHistory', 'Caching']
    assert caps[-1].messages is True


def test_one_shot_capabilities_gives_the_prefix_profile():
    services = SimpleNamespace(config=SimpleNamespace(models=_models()))
    caps = one_shot_capabilities(services)
    assert [type(c) for c in caps] == [Caching]
    assert caps[0].messages is False


def test_every_agent_construction_passes_capabilities():
    """Adoption guard (#338): a new agent must not ship without capabilities.

    The regression this ticket fixes is structural — eight agent
    constructions were added over time with no capabilities, so the claims
    retry replayed the full grown history with no compaction guard. Scanning
    the source is the only check that stays true for agents nobody has
    written yet.
    """
    import ast
    from pathlib import Path

    missing = []
    for path in sorted(Path('src/codingdude').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, 'id', None) != 'Agent':
                continue
            keywords = {k.arg for k in node.keywords if k.arg}
            if 'capabilities' not in keywords:
                missing.append(f'{path.name}:{node.lineno}')
    assert missing == [], (
        'Agent(...) without capabilities — use agent_caps.cache_capabilities: '
        + ', '.join(missing)
    )
