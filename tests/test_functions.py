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
"""DE-7a (#298): the six-function registry, per-function model config, and
the function tag on usage records (M6 cost attribution)."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from codingdude.config import (
    Config,
    FunctionModelConfig,
    ModelLineupIn,
    _default_lineup_dict,
    load_config,
    models_payload,
    save_models,
)
from codingdude.functions import (
    FUNCTIONS,
    function_spec,
    resolve_function_config,
)


def _config(**model_overrides) -> Config:
    models = Config.defaults().models
    if model_overrides:
        models = replace(models, **model_overrides)
    return replace(Config.defaults(), models=models)


# ---- the registry: six functions, locked policies, overlays ----


def test_registry_has_exactly_six_functions():
    assert set(FUNCTIONS) == {
        'designer', 'architect', 'coder', 'debugger',
        'evaluator', 'researcher',
    }


def test_tool_policy_is_registry_locked_and_restricted():
    for spec in FUNCTIONS.values():
        assert spec.tool_policy, spec.name
        # the delegation safety contract: no delegate session may gain
        # shell/edit/delegation capability, whatever the registry says
        assert 'shell' not in spec.tool_policy, spec.name
        assert 'edit' not in spec.tool_policy, spec.name
        assert 'delegation' not in spec.tool_policy, spec.name


def test_researcher_reads_the_web_evaluator_does_not():
    assert 'web' in FUNCTIONS['researcher'].tool_policy
    assert 'web' not in FUNCTIONS['evaluator'].tool_policy


def test_each_function_has_overlay_and_recommendation():
    for spec in FUNCTIONS.values():
        assert spec.overlay.strip(), spec.name
        assert spec.recommended.strip(), spec.name


def test_unknown_function_has_no_spec():
    assert function_spec('chief-of-staff') is None


# ---- the resolution chain: explicit -> subagent -> main ----


def test_explicit_profile_wins():
    cfg = _config(functions={
        'evaluator': FunctionModelConfig(
            model='zai:glm-5.3-flash', thinking='low'),
    })
    assert resolve_function_config(cfg, 'evaluator') == (
        'zai:glm-5.3-flash', 'low')


def test_absent_profile_falls_back_to_subagent_slot():
    cfg = _config()
    model, thinking = resolve_function_config(cfg, 'coder')
    assert model == cfg.models.subagent
    assert thinking == cfg.models.thinking


def test_profile_without_thinking_falls_back_to_global_thinking():
    cfg = _config(thinking='medium', functions={
        'debugger': FunctionModelConfig(model='deepseek:deepseek-v4-flash'),
    })
    _, thinking = resolve_function_config(cfg, 'debugger')
    assert thinking == 'medium'


def test_explicit_thinking_none_falls_back_to_global():
    cfg = _config(thinking='medium', functions={
        'debugger': FunctionModelConfig(
            model='deepseek:deepseek-v4-flash', thinking=None),
    })
    _, thinking = resolve_function_config(cfg, 'debugger')
    assert thinking == 'medium'


def test_resolve_unknown_function_returns_none():
    assert resolve_function_config(_config(), 'minister') is None


# ---- config load: fail-fast on bad [models.functions] ----


def test_load_config_fail_fast_on_unknown_function(home):
    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models.functions.chief]\nmodel = "zai:glm-5.3"\n',
        encoding='utf-8')
    with pytest.raises(ValueError, match='chief'):
        load_config()


def test_load_config_fail_fast_on_model_without_provider(home):
    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models.functions.evaluator]\nmodel = "glm-5.3"\n',
        encoding='utf-8')
    with pytest.raises(ValueError, match='provider:model'):
        load_config()


def test_load_config_fail_fast_on_unknown_entry_keys(home):
    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models.functions.evaluator]\n'
        'model = "zai:glm-5.3"\ntemperature = 0.5\n',
        encoding='utf-8')
    with pytest.raises(ValueError, match='temperature'):
        load_config()


def test_load_config_fail_fast_on_bad_thinking(home):
    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models.functions.evaluator]\n'
        'model = "zai:glm-5.3"\nthinking = "bogus"\n',
        encoding='utf-8')
    with pytest.raises(ValueError, match='thinking'):
        load_config()


def test_functions_load_and_default_to_empty(home):
    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models.functions.evaluator]\n'
        'model = "zai:glm-5.3-flash"\nthinking = "low"\n',
        encoding='utf-8')
    cfg = load_config()
    assert cfg.models.functions['evaluator'].model == 'zai:glm-5.3-flash'
    assert cfg.models.functions['evaluator'].thinking == 'low'
    # absent config = today's behavior: no function overrides at all
    assert Config.defaults().models.functions == {}


# ---- PUT /config/models validation (ModelLineupIn) ----


def _lineup(**patch) -> dict:
    return {**_default_lineup_dict(), **patch}


def test_lineup_in_rejects_unknown_function():
    with pytest.raises(ValidationError, match='chief'):
        ModelLineupIn(**_lineup(functions={
            'chief': {'model': 'zai:glm-5.3'}}))


def test_lineup_in_rejects_extra_entry_keys():
    with pytest.raises(ValidationError, match='temperature'):
        ModelLineupIn(**_lineup(functions={
            'evaluator': {'model': 'zai:glm-5.3', 'temperature': 1}}))


def test_lineup_in_rejects_model_without_provider():
    with pytest.raises(ValidationError):
        ModelLineupIn(**_lineup(functions={
            'evaluator': {'model': 'glm-5.3'}}))


def test_lineup_in_accepts_functions_table():
    parsed = ModelLineupIn(**_lineup(functions={
        'evaluator': {'model': 'zai:glm-5.3-flash', 'thinking': 'low'}}))
    assert parsed.functions['evaluator'].model == 'zai:glm-5.3-flash'
    assert parsed.functions['evaluator'].thinking == 'low'


# ---- save_models merge semantics ----


def test_save_models_round_trips_functions(home):
    home.mkdir(parents=True, exist_ok=True)
    save_models(home, {'functions': {
        'evaluator': {'model': 'zai:glm-5.3-flash', 'thinking': 'low'}}})
    cfg = load_config(home)
    assert cfg.models.functions['evaluator'].model == 'zai:glm-5.3-flash'
    assert cfg.models.functions['evaluator'].thinking == 'low'


def test_save_models_clears_function_entry_on_null(home):
    home.mkdir(parents=True, exist_ok=True)
    save_models(home, {'functions': {
        'evaluator': {'model': 'zai:glm-5.3-flash'}}})
    save_models(home, {'functions': None})
    assert load_config(home).models.functions == {}


def test_save_models_rejects_unknown_function(home):
    home.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match='chief'):
        save_models(home, {'functions': {
            'chief': {'model': 'zai:glm-5.3'}}})


# ---- per-project [models] override (#210 path) ----


def test_project_override_functions(tmp_path, home):
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.toml').write_text(
        '[models.functions.evaluator]\nmodel = "zai:glm-5.3-flash"\n',
        encoding='utf-8')
    cfg = load_config(home)
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    (workdir / '.codingdude.toml').write_text(
        '[models.functions.evaluator]\nmodel = "deepseek:deepseek-v4-flash"\n',
        encoding='utf-8')
    from codingdude.config import apply_project_models

    merged = apply_project_models(cfg, workdir)
    assert merged.models.functions['evaluator'].model == (
        'deepseek:deepseek-v4-flash')
    # the global config object is untouched
    assert cfg.models.functions['evaluator'].model == 'zai:glm-5.3-flash'


def test_project_override_invalid_functions_falls_back_to_global(
        tmp_path, home, caplog):
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.toml').write_text(
        '[models.functions.evaluator]\nmodel = "zai:glm-5.3-flash"\n',
        encoding='utf-8')
    cfg = load_config(home)
    workdir = tmp_path / 'proj'
    workdir.mkdir()
    (workdir / '.codingdude.toml').write_text(
        '[models.functions.minister]\nmodel = "zai:glm-5.3"\n',
        encoding='utf-8')
    from codingdude.config import apply_project_models

    merged = apply_project_models(cfg, workdir)
    assert merged.models.functions['evaluator'].model == 'zai:glm-5.3-flash'


# ---- GET /config/models payload ----


def test_models_payload_exposes_functions_and_specs():
    cfg = _config(functions={
        'evaluator': FunctionModelConfig(
            model='zai:glm-5.3-flash', thinking='low')})
    payload = models_payload(cfg)
    assert payload['functions']['evaluator'] == {
        'model': 'zai:glm-5.3-flash', 'thinking': 'low'}
    assert {s['name'] for s in payload['function_specs']} == set(FUNCTIONS)
    for spec in payload['function_specs']:
        assert spec['recommended'].strip()
        assert spec['tool_policy']


def test_models_payload_functions_default_empty():
    assert models_payload(_config())['functions'] == {}


# ---- M6: usage records carry the function tag ----


def test_record_usage_carries_function_tag(tmp_path):
    from codingdude.db import Database

    db = Database.connect(tmp_path / 'home')
    session_id = db.create_session(tmp_path)
    db.record_usage(
        session_id, model='zai:glm-5.3-flash', requests=2,
        input_tokens=100, output_tokens=50, function_name='evaluator')
    db.record_usage(
        session_id, model='deepseek:deepseek-v4-pro', requests=5,
        input_tokens=1000, output_tokens=500)
    usage = db.session_usage(session_id)
    by_function = {r['function_name']: r for r in usage['by_function']}
    assert by_function['evaluator']['requests'] == 2
    # untagged rows (main-session spend) group under None
    assert by_function[None]['requests'] == 5
    by_request = usage['by_request']
    assert by_request[0]['function_name'] == 'evaluator'
    assert by_request[1]['function_name'] is None


def test_usage_function_name_migration_on_legacy_db(tmp_path):
    """A pre-#298 database gains the function_name column additively."""
    import sqlite3

    home = tmp_path / 'legacy'
    home.mkdir()
    conn = sqlite3.connect(home / 'codingdude.db')
    conn.executescript(
        'CREATE TABLE usage (id INTEGER PRIMARY KEY AUTOINCREMENT,'
        ' session_id TEXT NOT NULL, model TEXT NOT NULL,'
        ' requests INTEGER NOT NULL DEFAULT 0,'
        ' input_tokens INTEGER NOT NULL DEFAULT 0,'
        ' output_tokens INTEGER NOT NULL DEFAULT 0,'
        ' cost_usd REAL, created_at TEXT NOT NULL);')
    conn.commit()
    conn.close()
    from codingdude.db import Database

    db = Database.connect(home)
    session_id = db.create_session(tmp_path)
    db.record_usage(
        session_id, model='zai:glm-5.3-flash', function_name='researcher')
    usage = db.session_usage(session_id)
    assert usage['by_function'][0]['function_name'] == 'researcher'
