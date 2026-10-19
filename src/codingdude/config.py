"""CodingDude configuration: model lineup and shell, stored under the home directory."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field, ValidationError, field_validator


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


# Providers the UI may bind models to; the prefix before ':' in "provider:model".
KNOWN_PROVIDERS = (
    'deepseek', 'zai', 'openai', 'anthropic', 'google', 'github',
    'groq', 'mistral', 'ollama', 'bedrock',
)

_THINKING_OFF_WORDS = ('off', 'none', 'false', 'disabled')


class ModelLineupIn(BaseModel):
    """Validated model-lineup payload for PUT /config/models (R50).

    Boundary validation: every field is checked here so an invalid save can
    never reach config.toml and brick the next boot.
    """

    model_config = {'extra': 'forbid'}

    main: str
    subagent: str
    fallback: str
    fallback_base_url: str | None = None
    vision: str | None = None
    thinking: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    context_limit: int | None = Field(default=None, ge=1)
    request_limit: int = Field(default=500, ge=1)
    pricing: dict[str, dict[str, float]] | None = None

    @field_validator('main', 'subagent', 'fallback', 'vision')
    @classmethod
    def _check_model_ref(cls, v: str | None) -> str | None:
        if v and ':' not in v:
            raise ValueError(
                f'{v!r} is not a provider-bound model — use "provider:model" '
                f'(e.g. "zai:glm-5.3"); known providers: {KNOWN_PROVIDERS}'
            )
        return v

    @field_validator('thinking')
    @classmethod
    def _check_thinking(cls, v: str | None) -> str | None:
        if v is None or v == '':
            return None
        val = v.strip().lower()
        if val not in THINKING_LEVELS and val not in _THINKING_OFF_WORDS:
            raise ValueError(
                f'invalid thinking level {v!r}; use one of {THINKING_LEVELS} or off'
            )
        return val

    @field_validator('pricing')
    @classmethod
    def _check_pricing(cls, v: dict[str, dict[str, float]] | None):
        if v is None:
            return None
        for model, rates in v.items():
            unknown = set(rates) - {'input', 'output'}
            if unknown:
                raise ValueError(f'pricing[{model}]: unknown keys {sorted(unknown)}')
        return v


def models_payload(config: Config) -> dict:
    """JSON-safe config view for GET /config/models: lineup + key presence only.

    Provider keys are surfaced as booleans — the API never echoes secret values.
    """
    env = os.environ
    providers = config.providers
    return {
        'models': {
            'main': config.models.main,
            'subagent': config.models.subagent,
            'fallback': config.models.fallback,
            'fallback_base_url': config.models.fallback_base_url,
            'vision': config.models.vision,
            'thinking': config.models.thinking,
            'max_tokens': config.models.max_tokens,
            'context_limit': config.models.context_limit,
            'request_limit': config.models.request_limit,
            'pricing': config.models.pricing,
        },
        'providers': {
            'deepseek': bool(providers.deepseek or env.get('DEEPSEEK_API_KEY')),
            'zai': bool(providers.zai or env.get('ZAI_API_KEY')),
            'github': bool(providers.github or env.get('GITHUB_PAT')),
        },
        'thinking_levels': THINKING_LEVELS,
        'warnings': _lineup_warnings(config.models),
    }


CODING_PLAN_BASE_URL = 'https://api.z.ai/api/coding/paas/v4'


def _lineup_warnings(lineup: ModelLineup) -> list[str]:
    """Advisories about a lineup that will likely misbehave.

    Z.AI has two subscription plans with different endpoints: coding-plan keys
    are rejected by the standard API, so a zai fallback without an explicit
    base url will fail (or bill the wrong plan) as soon as it is used.
    """
    out: list[str] = []
    if lineup.fallback.startswith('zai:') and not lineup.fallback_base_url:
        out.append(
            f'fallback is {lineup.fallback} but fallback_base_url is unset — '
            f'GLM Coding Plan keys require {CODING_PLAN_BASE_URL}'
        )
    return out


def save_models(home: Path, payload: dict) -> dict:
    """Validate and persist the model lineup; returns the merged lineup dict.

    Merge semantics, not replacement: only the fields present in the payload
    change. An explicit null clears a field; an omitted field keeps its stored
    value. Clients post whatever they render, so a replacing write silently
    erased settings the UI never showed — notably `fallback_base_url`, the
    GLM coding-plan endpoint, which drops z.ai back onto the standard API
    (coding-plan keys are rejected there).

    The merged result is what gets validated (not the fragment), so a partial
    save is checked against the lineup it produces. Every other config.toml
    section (shell, providers, delegation) is left untouched, and validation
    happens before any write, so a bad payload cannot brick the next boot.
    """
    config_path = home / 'config.toml'
    try:
        raw = tomllib.loads(config_path.read_text(encoding='utf-8'))
    except (tomllib.TOMLDecodeError, OSError):
        raw = {}

    patch = dict(payload or {})
    unknown = set(patch) - set(ModelLineupIn.model_fields)
    if unknown:
        raise ValueError(f'unknown model settings: {sorted(unknown)}')

    merged = dict(raw.get('models') or {})
    known = {k: v for k, v in merged.items() if k in ModelLineupIn.model_fields}
    known.update(patch)
    try:
        validated = ModelLineupIn(**{**_default_lineup_dict(), **known})
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    for name in patch:
        value = getattr(validated, name)
        if value is None:
            merged.pop(name, None)
        else:
            merged[name] = value
    raw['models'] = merged

    import tomli_w

    text = tomli_w.dumps(raw)
    tmp = config_path.with_suffix('.toml.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(config_path)
    return merged


def _default_lineup_dict() -> dict:
    """Default lineup as a plain dict — fills required fields a patch omits."""
    from dataclasses import asdict

    return {k: v for k, v in asdict(Config.defaults().models).items() if v is not None}


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
