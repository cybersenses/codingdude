"""#210: per-project [models] overrides from the workdir's .codingdude.toml."""

from codingdude.config import apply_project_models, load_config

_GLOBAL = (
    '[models]\nmain = "deepseek:deepseek-v4-pro"\n'
    'subagent = "deepseek:deepseek-v4-flash"\nfallback = "zai:glm-5.3"\n'
)


def _global_config(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.toml').write_text(_GLOBAL, encoding='utf-8')
    return load_config()


def test_project_models_override_wins_fieldwise(home, tmp_path):
    """.codingdude.toml [models] overrides only the fields it sets."""
    config = _global_config(home)
    (tmp_path / '.codingdude.toml').write_text(
        '[models]\nmain = "zai:glm-5.3"\nthinking = "high"\n', encoding='utf-8'
    )
    merged = apply_project_models(config, tmp_path)
    assert merged.models.main == 'zai:glm-5.3'
    assert merged.models.thinking == 'high'
    # Fields not overridden keep the global value.
    assert merged.models.subagent == 'deepseek:deepseek-v4-flash'
    assert merged.models.fallback == 'zai:glm-5.3'
    # The global config object is untouched.
    assert config.models.main == 'deepseek:deepseek-v4-pro'


def test_project_models_invalid_falls_back_to_global(home, tmp_path):
    """A broken project override must not brick the run: warn + global lineup."""
    config = _global_config(home)
    (tmp_path / '.codingdude.toml').write_text(
        '[models]\nmain = "no-provider-prefix"\n', encoding='utf-8'
    )
    merged = apply_project_models(config, tmp_path)
    assert merged.models.main == 'deepseek:deepseek-v4-pro'


def test_project_models_unknown_keys_ignored(home, tmp_path):
    config = _global_config(home)
    (tmp_path / '.codingdude.toml').write_text(
        '[models]\nbogus_key = 1\nmain = "zai:glm-5.3"\n', encoding='utf-8'
    )
    merged = apply_project_models(config, tmp_path)
    assert merged.models.main == 'zai:glm-5.3'


def test_project_models_absent_file_unchanged(home, tmp_path):
    config = _global_config(home)
    assert apply_project_models(config, tmp_path) is config
