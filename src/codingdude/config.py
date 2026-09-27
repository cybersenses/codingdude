"""CodingDude configuration: model lineup and shell, stored under the home directory."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast


def _default_config_toml(lineup: ModelLineup) -> str:
    return (
        '# CodingDude configuration. Edit freely; missing values fall back to defaults.\n'
        '[models]\n'
        f'main = "{lineup.main}"\n'
        f'subagent = "{lineup.subagent}"\n'
        f'fallback = "{lineup.fallback}"\n'
        '# Thinking depth for GLM models: minimal | low | medium | high | xhigh | off\n'
        '# (cost lever: low/medium while testing; unset = provider default)\n'
        '# thinking = "low"\n'
        '# Max model requests per run (pydantic-ai default 50 is too low for\n'
        '# long agentic sessions)\n'
        '# request_limit = 500\n'
        '\n[shell]\n'
        '# "bash" (Git Bash) or "powershell"\n'
        'default = "bash"\n'
    )


@dataclass(frozen=True)
class ModelLineup:
    """Ordered model fallback lineup with per-model provider binding."""
    main: str
    subagent: str
    fallback: str
    # Optional endpoint override for the fallback provider, e.g. the GLM
    # coding-plan endpoint (https://api.z.ai/api/coding/paas/v4) for
    # coding-plan keys that are not valid against the normal Z.AI API.
    fallback_base_url: str | None = None
    # Vision-capable model for image input (e.g. "zai:glm-5v"). Image prompts
    # route here; None disables image input.
    vision: str | None = None
    # Thinking depth for models that support it (ZAI GLM profiles): one of
    # minimal | low | medium | high | xhigh (or off/none to disable). None
    # leaves provider defaults. Cost lever: low/medium while testing.
    thinking: str | None = None
    # Max response tokens (None = provider default). Increase if the model
    # hits the provider token limit before finishing its response.
    max_tokens: int | None = None
    # Context window (tokens) override for the main model. None = inferred
    # from the model name (see context.model_limit_for). Drives compaction
    # timing and the UI context meter.
    context_limit: int | None = None
    # Max model requests per run. pydantic-ai defaults to 50, which a long
    # agentic session exhausts; raise it so long runs aren't cut off.
    request_limit: int = 500
    # Cost rates per model (R10): name-or-substring -> USD per 1M tokens.
    # e.g. pricing = { deepseek-v4-pro = { input = 0.27, output = 1.1 } }
    # Models without an entry are 'unpriced' (tokens-only accounting).
    pricing: dict[str, dict[str, float]] | None = None


THINKING_LEVELS = ('minimal', 'low', 'medium', 'high', 'xhigh')
ThinkingLevel = Literal['minimal', 'low', 'medium', 'high', 'xhigh']
ThinkingSetting = bool | ThinkingLevel


def parse_thinking(value: str | None) -> ThinkingSetting | None:
    """Config string -> pydantic-ai `thinking` setting (bool | level | None)."""
    if value is None or value == '':
        return None
    val = value.strip().lower()
    if val in ('off', 'none', 'false', 'disabled'):
        return False
    if val in THINKING_LEVELS:
        return cast(ThinkingLevel, val)
    raise ValueError(f'invalid thinking level {value!r}; use one of {THINKING_LEVELS} or off')


@dataclass(frozen=True)
class DelegationConfig:
    """Budget ceiling for one `delegate` call (R13): the subagent is aborted
    with a readable tool result instead of burning the session budget."""

    max_requests: int = 40
    max_cost_usd: float | None = None


@dataclass(frozen=True)
class ShellConfig:
    """Shell command allow/deny policy configuration."""
    default: str = 'bash'


@dataclass(frozen=True)
class ProviderKeys:
    """API keys per provider, read from the environment at load time."""
    deepseek: str | None = None
    zai: str | None = None
    github: str | None = None


@dataclass(frozen=True)
class Config:
    """Top-level CodingDude configuration assembled from config home + environment."""
    models: ModelLineup
    shell: ShellConfig
    providers: ProviderKeys = field(default_factory=ProviderKeys)
    delegation: DelegationConfig = field(default_factory=DelegationConfig)

    @classmethod
    def defaults(cls) -> Config:
        return cls(
            models=ModelLineup(
                main='deepseek:deepseek-v4-pro',
                subagent='deepseek:deepseek-v4-flash',
                fallback='zai:glm-5.3',
            ),
            shell=ShellConfig(default='bash'),
            providers=ProviderKeys(),
        )


def config_home() -> Path:
    """Resolve the CodingDude config home directory (override via env)."""
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

    try:
        raw = tomllib.loads(config_path.read_text(encoding='utf-8'))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logging.getLogger(__name__).warning(
            'invalid config.toml (%s); using defaults', exc
        )
        return defaults
    models = raw.get('models', {})
    shell = raw.get('shell', {})
    providers = raw.get('providers', {})
    delegation_raw = raw.get('delegation', {})
    delegation = DelegationConfig(
        max_requests=delegation_raw.get(
            'max_requests', defaults.delegation.max_requests),
        max_cost_usd=delegation_raw.get(
            'max_cost_usd', defaults.delegation.max_cost_usd),
    )
    config = Config(
        models=ModelLineup(
            main=models.get('main', defaults.models.main),
            subagent=models.get('subagent', defaults.models.subagent),
            fallback=models.get('fallback', defaults.models.fallback),
            fallback_base_url=models.get('fallback_base_url', defaults.models.fallback_base_url),
            vision=models.get('vision', defaults.models.vision),
            thinking=models.get('thinking', defaults.models.thinking),
            max_tokens=models.get('max_tokens', defaults.models.max_tokens),
            context_limit=models.get('context_limit', defaults.models.context_limit),
            request_limit=models.get('request_limit', defaults.models.request_limit),
            pricing=models.get('pricing', defaults.models.pricing),
        ),
        shell=ShellConfig(default=shell.get('default', defaults.shell.default)),
        providers=ProviderKeys(
            deepseek=providers.get('deepseek'),
            zai=providers.get('zai'),
            github=providers.get('github'),
        ),
        delegation=delegation,
    )
    apply_provider_keys(config)
    return config


def apply_provider_keys(config: Config) -> None:
    """Config-stored keys are the low-precedence fallback; env vars win."""
    if config.providers.deepseek:
        os.environ.setdefault('DEEPSEEK_API_KEY', config.providers.deepseek)
    if config.providers.zai:
        os.environ.setdefault('ZAI_API_KEY', config.providers.zai)
    if config.providers.github:
        os.environ.setdefault('GITHUB_PAT', config.providers.github)


def load_project_config(workdir: Path) -> dict:
    """Per-project overrides from `.codingdude.toml` in the Workdir (currently: shell)."""
    path = workdir / '.codingdude.toml'
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text(encoding='utf-8'))
    out: dict = {}
    shell = raw.get('shell')
    # Accept the documented top-level string (`shell = "powershell"`) and the
    # global-config table shape (`[shell] default = ...` / `[shell] shell = ...`).
    if isinstance(shell, str):
        out['shell'] = shell
    elif isinstance(shell, dict):
        value = shell.get('default') or shell.get('shell')
        if value:
            out['shell'] = value
    return out
