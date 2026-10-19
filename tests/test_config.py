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
"""Config: defaults, first-run creation, and reading back an existing config."""

from codingdude.config import Config, load_config


def test_first_run_creates_config_with_model_defaults(home):
    config = load_config()
    assert config.models.main == 'deepseek:deepseek-v4-pro'
    assert config.models.subagent == 'deepseek:deepseek-v4-flash'
    assert config.models.fallback == 'zai:glm-5.3'
    assert config.shell.default == 'bash'
    assert (home / 'config.toml').exists()


def test_request_limit_defaults_above_library_default(home):
    """pydantic-ai caps a run at 50 model requests by default, which kills
    long agentic sessions — CodingDude must raise it (configurable)."""
    config = load_config()
    assert config.models.request_limit > 50


def test_request_limit_override_is_read(home):
    home.mkdir(parents=True)
    (home / 'config.toml').write_text(
        '[models]\nrequest_limit = 999\n', encoding='utf-8'
    )
    assert load_config().models.request_limit == 999


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


def test_save_models_preserves_other_sections(home):
    """A models save must never lose shell/providers/delegation (key-loss incident)."""
    from codingdude.config import save_models

    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.toml').write_text(
        '[models]\nmain = "deepseek:deepseek-flash"\n'
        '[shell]\ndefault = "bash"\n'
        '[providers]\nzai = "real-secret-key"\n'
        '[delegation]\nmax_cost_usd = 5.0\n',
        encoding='utf-8',
    )
    save_models(home, {'thinking': 'medium'})
    text = (home / 'config.toml').read_text(encoding='utf-8')
    assert 'real-secret-key' in text
    assert 'default = "bash"' in text
    assert 'max_cost_usd = 5.0' in text
    assert 'thinking = "medium"' in text


def test_save_models_refuses_corrupt_config(home):
    """An unparseable config must block the save, not be replaced by a models-only file."""
    import pytest

    from codingdude.config import save_models

    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.toml').write_text('not valid toml [[[', encoding='utf-8')
    with pytest.raises(ValueError, match='refusing to overwrite'):
        save_models(home, {'thinking': 'low'})
    assert (home / 'config.toml').read_text(encoding='utf-8') == 'not valid toml [[['
