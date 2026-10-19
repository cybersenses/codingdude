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
