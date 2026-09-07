"""CodingDude configuration: model lineup and shell, stored under the home directory."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

def _default_config_toml(lineup: ModelLineup) -> str:
    return (
        '# CodingDude configuration. Edit freely; missing values fall back to defaults.\n'
        '[models]\n'
        f'main = "{lineup.main}"\n'
        f'subagent = "{lineup.subagent}"\n'
        f'fallback = "{lineup.fallback}"\n\n'
        '[shell]\n'
        '# "bash" (Git Bash) or "powershell"\n'
        'default = "bash"\n'
    )


@dataclass(frozen=True)
class ModelLineup:
    main: str
    subagent: str
    fallback: str


@dataclass(frozen=True)
class ShellConfig:
    default: str = 'bash'


@dataclass(frozen=True)
class Config:
    models: ModelLineup
    shell: ShellConfig

    @classmethod
    def defaults(cls) -> 'Config':
        return cls(
            models=ModelLineup(
                main='deepseek:deepseek-v4-pro',
                subagent='deepseek:deepseek-v4-flash',
                fallback='zai:glm-5.3',
            ),
            shell=ShellConfig(default='bash'),
        )


def config_home() -> Path:
    return Path(os.environ.get('CODEDUDE_HOME', Path.home() / '.codingdude'))


def load_config(home: Path | None = None) -> Config:
    """Load config from `home` (default: CODEDUDE_HOME / ~/.codingdude).

    Creates the directory and a default config.toml on first use; an existing
    file is read as-is, with missing values falling back to defaults.
    """
    home = home or config_home()
    config_path = home / 'config.toml'
    defaults = Config.defaults()

    if not config_path.exists():
        home.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            _default_config_toml(defaults.models), encoding='utf-8'
        )
        return defaults

    raw = tomllib.loads(config_path.read_text(encoding='utf-8'))
    models = raw.get('models', {})
    shell = raw.get('shell', {})
    return Config(
        models=ModelLineup(
            main=models.get('main', defaults.models.main),
            subagent=models.get('subagent', defaults.models.subagent),
            fallback=models.get('fallback', defaults.models.fallback),
        ),
        shell=ShellConfig(default=shell.get('default', defaults.shell.default)),
    )
