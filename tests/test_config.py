"""Config: defaults, first-run creation, and reading back an existing config."""

from codingdude.config import Config, load_config


def test_first_run_creates_config_with_model_defaults(home):
    config = load_config()
    assert config.models.main == 'deepseek:deepseek-v4-pro'
    assert config.models.subagent == 'deepseek:deepseek-v4-flash'
    assert config.models.fallback == 'zai:glm-5.3'
    assert config.shell.default == 'bash'
    assert (home / 'config.toml').exists()


def test_existing_config_is_read_not_overwritten(home):
    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models]\nmain = "deepseek:deepseek-reasoner"\n'
        'subagent = "deepseek:deepseek-v4-flash"\nfallback = "zai:glm-5.3"\n'
        '[shell]\ndefault = "powershell"\n'
    )
    config = load_config()
    assert config.models.main == 'deepseek:deepseek-reasoner'
    assert config.shell.default == 'powershell'


def test_defaults_constant_matches_written_config(home):
    load_config()
    assert Config.defaults().models.main == 'deepseek:deepseek-v4-pro'


def test_thinking_level_round_trip(home):
    import pytest

    from codingdude.config import parse_thinking

    assert parse_thinking(None) is None
    assert parse_thinking('') is None
    assert parse_thinking('low') == 'low'
    assert parse_thinking(' LOW ') == 'low'
    assert parse_thinking('off') is False
    with pytest.raises(ValueError):
        parse_thinking('bogus')

    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models]\nmain = "deepseek:deepseek-flash"\n'
        'subagent = "deepseek:deepseek-flash"\nfallback = "zai:glm-5.3-flash"\n'
        'thinking = "low"\n'
    )
    config = load_config()
    assert config.models.thinking == 'low'
    assert config.models.main == 'deepseek:deepseek-flash'


def test_context_limit_round_trip(home):
    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models]\nmain = "deepseek:deepseek-flash"\n'
        'subagent = "deepseek:deepseek-flash"\nfallback = "zai:glm-5.3-flash"\n'
        'context_limit = 64000\n'
    )
    assert load_config().models.context_limit == 64000
    # Absent key -> None (limit inferred from the model name instead).
    home.mkdir(exist_ok=True)
    (home / 'config.toml').write_text(
        '[models]\nmain = "deepseek:deepseek-flash"\n'
        'subagent = "deepseek:deepseek-flash"\nfallback = "zai:glm-5.3-flash"\n'
    )
    assert load_config().models.context_limit is None
