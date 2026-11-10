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
"""Arbitrary user-defined providers (#212): any OpenAI-compatible endpoint,
configurable from the Settings UI, selectable at runtime.

Seams under test:
- load_config: `[providers.<name>]` tables + legacy string shorthand
- save_provider_keys / models_payload: full-def round-trip, sentinel contract
- ModelLineupIn: any `x:y` prefix accepted for custom providers
- _model_from_name: custom provider -> OpenAI-compatible model on its base_url
- verify_provider_keys: generic per-provider smoke
"""

import os
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from codingdude.config import (
    SECRET_MASK,
    Config,
    ProviderDef,
    load_config,
    models_payload,
    save_provider_keys,
    verify_provider_keys,
)
from codingdude.server import create_app

TEST_TOKEN = 'cd-' + 'integration'
OR_URL = 'https://openrouter.ai/api/v1'
OR_KEY = 'stored-' + 'openrouter-key'
ENV_VALUE = 'a' * 12  # dummy credential value for env-var plumbing tests


def client(tmp_path, monkeypatch=None):
    os.environ['CODEDUDE_HOME'] = str(tmp_path / 'home')
    if monkeypatch:
        for n in ('ZAI_API_KEY', 'DEEPSEEK_API_KEY', 'GITHUB_PAT',
                  'OPENROUTER_API_KEY'):
            monkeypatch.delenv(n, raising=False)
    app = create_app(home=tmp_path / 'home', token=TEST_TOKEN, allow_testclient=True)
    return TestClient(app, headers={'Authorization': f'Bearer {TEST_TOKEN}'})


def test_load_config_parses_provider_tables_and_legacy_strings(tmp_path, monkeypatch):
    for n in ('ZAI_API_KEY', 'DEEPSEEK_API_KEY', 'OPENROUTER_API_KEY'):
        monkeypatch.delenv(n, raising=False)
    cfg_path = tmp_path / 'home' / 'config.toml'
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        '[providers]\nzai = "legacy-key"\n'
        f'[providers.openrouter]\napi_key = "{OR_KEY}"\n'
        f'base_url = "{OR_URL}"\n', encoding='utf-8')
    cfg = load_config(cfg_path.parent)
    assert cfg.providers['zai'] == ProviderDef(api_key='legacy-key')
    assert cfg.providers['openrouter'].api_key == OR_KEY
    assert cfg.providers['openrouter'].base_url == OR_URL


def test_provider_env_var_mapping():
    from codingdude.config import provider_env_var

    assert provider_env_var('zai') == 'ZAI_API_KEY'
    assert provider_env_var('github') == 'GITHUB_PAT'
    assert provider_env_var('openrouter') == 'OPENROUTER_API_KEY'
    assert provider_env_var('my-broker') == 'MY_BROKER_API_KEY'


def test_save_provider_full_def_roundtrip_and_delete(tmp_path):
    home = tmp_path / 'home'
    home.mkdir(parents=True)
    (home / 'config.toml').write_text('', encoding='utf-8')
    saved = save_provider_keys(home, {
        'openrouter': {'api_key': OR_KEY, 'base_url': OR_URL}})
    assert saved == {'openrouter': True}
    raw = tomllib.loads((home / 'config.toml').read_text(encoding='utf-8'))
    assert raw['providers']['openrouter']['api_key'] == OR_KEY
    assert raw['providers']['openrouter']['base_url'] == OR_URL
    # sentinel keeps the stored value; base_url can be updated independently
    save_provider_keys(home, {'openrouter': {
        'api_key': SECRET_MASK, 'base_url': 'https://other.example/v1'}})
    raw = tomllib.loads((home / 'config.toml').read_text(encoding='utf-8'))
    assert raw['providers']['openrouter']['api_key'] == OR_KEY
    assert raw['providers']['openrouter']['base_url'] == 'https://other.example/v1'
    # null deletes the whole provider
    save_provider_keys(home, {'openrouter': None})
    raw = tomllib.loads((home / 'config.toml').read_text(encoding='utf-8'))
    assert 'openrouter' not in raw.get('providers', {})


def test_save_provider_rejects_bad_names_and_fields(tmp_path):
    home = tmp_path / 'home'
    home.mkdir(parents=True)
    (home / 'config.toml').write_text('', encoding='utf-8')
    for bad in ('', 'has space', 'x:y'):
        try:
            save_provider_keys(home, {bad: OR_KEY})
            raise AssertionError(f'{bad!r} accepted')
        except ValueError:
            pass
    try:
        save_provider_keys(home, {'ok-name': {'bogus': 1}})
        raise AssertionError('bogus field accepted')
    except ValueError:
        pass


def test_models_payload_masks_and_lists_custom_providers(tmp_path, monkeypatch):
    monkeypatch.delenv('ZAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    cfg_path = tmp_path / 'home' / 'config.toml'
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        f'[providers.openrouter]\napi_key = "{OR_KEY}"\n'
        f'base_url = "{OR_URL}"\n', encoding='utf-8')
    payload = models_payload(load_config(cfg_path.parent))
    assert payload['providers'] == {'openrouter': SECRET_MASK}
    assert payload['provider_defs']['openrouter']['base_url'] == OR_URL
    assert 'openrouter' in payload['provider_prefixes']
    assert 'zai' in payload['provider_prefixes']  # native list kept


def test_model_ref_accepts_any_prefix(tmp_path):
    c = client(tmp_path)
    r = c.put('/config/models', json={'models': {'main': 'openrouter:some/model'}})
    assert r.status_code == 200, r.text
    r = c.put('/config/models', json={'models': {'main': 'no-prefix'}})
    assert r.status_code == 422


def test_api_custom_provider_roundtrip(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.put('/config/models', json={'providers': {
        'openrouter': {'api_key': OR_KEY, 'base_url': OR_URL}}})
    assert r.status_code == 200, r.text
    body = c.get('/config/models').json()
    assert body['providers']['openrouter'] == '__codingdude_key_set__'
    assert body['provider_defs']['openrouter']['base_url'] == OR_URL
    assert OR_KEY not in str(body)
    # a model bound to it validates and persists
    r = c.put('/config/models', json={
        'models': {'main': 'openrouter:some/model'}})
    assert r.status_code == 200, r.text
    cfg = load_config(Path(os.environ['CODEDUDE_HOME']))
    assert cfg.models.main == 'openrouter:some/model'


def test_model_from_name_custom_provider_uses_base_url(monkeypatch):
    from codingdude.engine import _model_from_name

    monkeypatch.setenv('OPENROUTER_API_KEY', ENV_VALUE)
    model = _model_from_name(
        'openrouter:qwen-3', None,
        providers={'openrouter': ProviderDef(base_url=OR_URL)})
    assert model.model_name == 'qwen-3'
    openai_client = model.client  # the AsyncOpenAI wired by the provider def
    assert str(openai_client.base_url).startswith(OR_URL)
    assert openai_client.api_key  # the provider env var value was picked up


def test_verify_provider_keys_generic(monkeypatch):
    for n in ('ZAI_API_KEY', 'DEEPSEEK_API_KEY', 'GITHUB_PAT',
              'OPENROUTER_API_KEY'):
        monkeypatch.delenv(n, raising=False)
    calls = []

    def fake_transport(url, headers, body):
        calls.append(url)
        return (200, '{}')

    from dataclasses import replace

    config = replace(Config.defaults(), providers={
        'openrouter': ProviderDef(api_key=OR_KEY, base_url=OR_URL)})
    results = verify_provider_keys(config, transport=fake_transport)
    assert results['openrouter'] == {
        'configured': True, 'ok': True, 'status': 200, 'detail': None}
    assert calls == [OR_URL + '/chat/completions']


def test_verify_skips_provider_without_base_url(monkeypatch):
    for n in ('ZAI_API_KEY', 'DEEPSEEK_API_KEY', 'GITHUB_PAT'):
        monkeypatch.delenv(n, raising=False)
    from dataclasses import replace

    config = replace(Config.defaults(), providers={
        'mystery': ProviderDef(api_key=OR_KEY)})
    results = verify_provider_keys(config, transport=None)
    assert results['mystery']['configured'] is True
    assert results['mystery']['ok'] is None
    assert 'base_url' in results['mystery']['detail']


def test_build_model_keeps_primary_when_fallback_unavailable(monkeypatch):
    """Fallback construction failure must degrade to the (custom-provider)
    primary, not discard it via infer_model (post-push review finding #3)."""
    import tempfile

    from codingdude.db import Database
    from codingdude.engine import Engine, _model_from_name

    monkeypatch.setenv('CODEDUDE_HOME', tempfile.mkdtemp())
    from dataclasses import replace

    cfg = replace(Config.defaults(), providers={
        'openrouter': ProviderDef(base_url=OR_URL)})
    cfg = replace(cfg, models=replace(cfg.models, fallback='bogus-provider:x'))
    engine = Engine(config=cfg, db=Database.connect(Path(os.environ['CODEDUDE_HOME'])))
    model = engine.build_model(main='openrouter:qwen-3')
    expected = _model_from_name('openrouter:qwen-3', None, cfg.providers)
    assert model.model_name == expected.model_name  # primary survived


def test_subagent_model_resolves_custom_provider(monkeypatch):
    """The subagent/extraction slot routes through _model_from_name (#212)."""
    from dataclasses import replace

    from pydantic_ai.models.openai import OpenAIChatModel

    from codingdude.engine import Engine

    cfg = Config.defaults()
    cfg = replace(cfg, models=replace(cfg.models, subagent='openrouter:cheap'))
    cfg = replace(cfg, providers={'openrouter': ProviderDef(base_url=OR_URL)})
    engine = Engine(config=cfg, db=None)  # type: ignore[arg-type]
    model = engine._build_subagent_model()
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == 'cheap'


def test_save_provider_clear_retracts_injected_env(tmp_path, monkeypatch):
    """Clearing/updating a stored key must not leave the old value winning
    in os.environ until restart (post-push review finding #9)."""
    home = tmp_path / 'home'
    home.mkdir(parents=True)
    (home / 'config.toml').write_text('', encoding='utf-8')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    save_provider_keys(home, {'openrouter': {'api_key': OR_KEY}})
    # load_config injects it (apply_provider_keys setdefault)
    load_config(home)
    assert os.environ['OPENROUTER_API_KEY'] == OR_KEY
    # clear the stored key -> the injected env value is retracted
    save_provider_keys(home, {'openrouter': {'api_key': None}})
    assert 'OPENROUTER_API_KEY' not in os.environ
    # update the key -> the new stored value applies without a restart
    new_key = 'rotated-' + OR_KEY
    save_provider_keys(home, {'openrouter': {'api_key': new_key}})
    assert os.environ['OPENROUTER_API_KEY'] == new_key


def test_verify_allows_http_on_localhost(monkeypatch):
    """Local OpenAI-compatible endpoints (Ollama, LM Studio) must be smoke-
    testable, not blanket-rejected as non-https (post-push review #8)."""
    for n in ('ZAI_API_KEY', 'DEEPSEEK_API_KEY', 'GITHUB_PAT'):
        monkeypatch.delenv(n, raising=False)
    from dataclasses import replace

    config = replace(Config.defaults(), providers={
        'ollama': ProviderDef(api_key=OR_KEY, base_url='http://127.0.0.1:11434/v1')})
    results = verify_provider_keys(config, timeout_s=1.0)
    # No server listening: a connection error, NOT the scheme rejection.
    assert 'non-https' not in (results['ollama']['detail'] or '')


# ---- R84a: the provider catalog (curated, runtime-verified entries) ----

def test_provider_catalog_lists_only_loadable_providers():
    """Every catalog entry's provider module must import in this install.
    groq/mistral/cohere/xai/bedrock need optional SDKs the shipped venv does
    not have — advertising them would fail exactly at the run the user
    configured them for."""
    from pydantic_ai.providers import infer_provider_class

    from codingdude.config import PROVIDER_CATALOG
    for name in PROVIDER_CATALOG:
        infer_provider_class(name)  # ImportError/ValueError here = catalog lie


def test_provider_catalog_wiring_facts():
    """Env vars and canonical endpoints, verified against the installed
    pydantic-ai provider sources (R84a fact-check, .scratch evidence)."""
    from codingdude.config import PROVIDER_CATALOG

    assert PROVIDER_CATALOG['openai'].env_var == 'OPENAI_API_KEY'
    assert PROVIDER_CATALOG['anthropic'].env_var == 'ANTHROPIC_API_KEY'
    assert PROVIDER_CATALOG['google'].env_var == 'GOOGLE_API_KEY'
    assert PROVIDER_CATALOG['deepseek'].env_var == 'DEEPSEEK_API_KEY'
    assert PROVIDER_CATALOG['zai'].env_var == 'ZAI_API_KEY'
    # pydantic-ai's GitHubProvider reads GITHUB_API_KEY only (no GITHUB_PAT
    # fallback) — the catalog carries the name the runtime actually resolves.
    assert PROVIDER_CATALOG['github'].env_var == 'GITHUB_API_KEY'
    assert PROVIDER_CATALOG['github'].base_url == 'https://models.github.ai/inference'
    assert PROVIDER_CATALOG['ollama'].needs_key is False
    assert PROVIDER_CATALOG['ollama'].base_url == 'http://localhost:11434/v1'
    assert PROVIDER_CATALOG['openrouter'].base_url == 'https://openrouter.ai/api/v1'


def test_models_payload_exposes_provider_catalog(tmp_path):
    home = tmp_path / 'home'
    home.mkdir(parents=True)
    payload = models_payload(load_config(home))
    catalog = payload['provider_catalog']
    names = [e['name'] for e in catalog]
    assert 'openai' in names and 'zai' in names
    entry = next(e for e in catalog if e['name'] == 'openrouter')
    assert entry['label'] == 'OpenRouter'
    assert entry['env_var'] == 'OPENROUTER_API_KEY'
    assert entry['base_url'] == 'https://openrouter.ai/api/v1'


def test_verify_uses_catalog_smoke_for_openai_compatible_entries(monkeypatch):
    """A catalog provider saved without an explicit base_url is smoke-tested
    against the catalog's canonical endpoint instead of 'untested'."""
    for n in ('ZAI_API_KEY', 'DEEPSEEK_API_KEY', 'GITHUB_PAT'):
        monkeypatch.delenv(n, raising=False)
    from dataclasses import replace

    calls = []

    def fake_transport(url, headers, body):
        calls.append(url)
        return (200, '{}')

    config = replace(Config.defaults(), providers={
        'openrouter': ProviderDef(api_key=OR_KEY),   # no base_url stored
        'openai': ProviderDef(api_key=OR_KEY),
    })
    results = verify_provider_keys(config, transport=fake_transport)
    assert results['openrouter']['ok'] is True
    assert results['openai']['ok'] is True
    assert 'https://openrouter.ai/api/v1/chat/completions' in calls
    assert 'https://api.openai.com/v1/chat/completions' in calls
    # A non-catalog name without base_url stays honestly untested.
    config2 = replace(Config.defaults(), providers={
        'mystery': ProviderDef(api_key=OR_KEY)})
    results2 = verify_provider_keys(config2, transport=fake_transport)
    assert results2['mystery']['ok'] is None
    assert 'base_url' in results2['mystery']['detail']
