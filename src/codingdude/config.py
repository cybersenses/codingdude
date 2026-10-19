"""CodingDude configuration: model lineup and shell, stored under the home directory."""

from __future__ import annotations

import logging
import os
import re
import tomllib
from dataclasses import dataclass, field, replace
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


# Providers the UI may suggest for model binding; the prefix before ':' in
# "provider:model". Any OTHER prefix is valid too when the user has defined a
# matching [providers.<name>] entry (#212) — this list is native pydantic-ai
# support plus the built-in trio, used for suggestions and error messages.
KNOWN_PROVIDERS = (
    'deepseek', 'zai', 'openai', 'anthropic', 'google', 'github',
    'groq', 'mistral', 'ollama', 'bedrock',
)

# Built-in providers keep their historical env-var names; custom providers
# default to <NAME>_API_KEY unless their [providers.<name>] table overrides
# `env_var`.
_LEGACY_ENV_VARS = {
    'zai': 'ZAI_API_KEY', 'deepseek': 'DEEPSEEK_API_KEY', 'github': 'GITHUB_PAT',
}

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
                f'(e.g. "zai:glm-5.3"); built-in providers: {KNOWN_PROVIDERS}, '
                'or any name you have defined under [providers.<name>]'
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
    """JSON-safe config view for GET /config/models: lineup + masked keys.

    Provider keys are surfaced as SECRET_MASK when set (never the value) and
    None when absent. The sentinel is what the UI echoes back on save; the
    PUT path ignores it, so a full round-trip cannot clobber a stored key.

    #212: providers are user-defined. `provider_defs` carries the non-secret
    definition fields (base_url, env_var) so the UI can edit them;
    `provider_prefixes` is the suggestion list for model bindings (built-in
    providers plus every configured custom one).
    """
    providers: dict[str, str | None] = {}
    provider_defs: dict[str, dict] = {}
    for name, d in config.providers.items():
        providers[name] = SECRET_MASK if provider_effective_key(name, d) else None
        defs = {k: getattr(d, k) for k in ('base_url', 'env_var')
                if getattr(d, k)}
        if defs:
            provider_defs[name] = defs

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
        'providers': providers,
        'provider_defs': provider_defs,
        'provider_prefixes': sorted(set(KNOWN_PROVIDERS) | set(config.providers)),
        'thinking_levels': THINKING_LEVELS,
        'warnings': _lineup_warnings(config.models),
    }


SECRET_MASK = ''.join(('__', 'codingdude_key', '_set__'))
"""Sentinel echoed by GET in place of a stored provider key. The PUT path
treats it as "unchanged" — this is the property that keeps a Settings
round-trip from ever writing a masked placeholder over a real key."""


_PROVIDER_NAME_OK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
_PROVIDER_FIELDS = ('api_key', 'base_url', 'env_var')


def _sync_env_keys(names: set, old_providers: dict, new_providers: dict) -> None:
    """Keep the running process's env in sync with a provider save (#212).

    apply_provider_keys setdefault-ed stored keys into os.environ; without
    this, updating or clearing a key in the UI leaves the OLD value winning
    (env beats stored) until the process restarts. For every touched
    provider, an env value that a stored key injected is retracted and the
    new stored key re-applied. A genuine user-set env var that differs from
    any stored key is never touched (and keeps winning, by design).
    """
    old_defs = _parse_providers(old_providers)
    new_defs = _parse_providers(new_providers)
    for name in names:
        for d in (old_defs.get(name), new_defs.get(name)):
            if d and d.api_key:
                var = d.env_var or provider_env_var(name)
                if os.environ.get(var) == d.api_key:
                    os.environ.pop(var, None)
        new = new_defs.get(name)
        if new and new.api_key:
            os.environ.setdefault(
                new.env_var or provider_env_var(name), new.api_key)


def save_provider_keys(home: Path, patch: dict) -> dict[str, bool]:
    """Merge provider definitions into config.toml's [providers] section.

    Per-entry semantics (#212):
    - str: SECRET_MASK -> ignored; ''/None -> key cleared; other -> key stored
      (existing base_url/env_var preserved).
    - dict: {api_key?, base_url?, env_var?} merged; SECRET_MASK api_key is
      ignored; null/'' fields are cleared; an empty result deletes the entry.
    - None: the whole provider entry is deleted.

    Returns presence booleans for every touched provider (never values).
    """
    config_path = home / 'config.toml'
    try:
        raw = tomllib.loads(config_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raw = {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f'existing config.toml is not valid TOML ({exc}); '
            'refusing to overwrite it — fix or remove the file first'
        ) from exc

    providers = dict(raw.get('providers') or {})
    old_providers = dict(providers)
    for name, value in patch.items():
        if not _PROVIDER_NAME_OK.match(name or ''):
            raise ValueError(
                f'invalid provider name {name!r}: use letters, digits, - or _')
        if value is None:
            providers.pop(name, None)
        elif isinstance(value, str):
            if value == SECRET_MASK:
                continue
            if value == '':
                _clear_provider_key(providers, name)
            else:
                _set_provider_key(providers, name, value)
        elif isinstance(value, dict):
            unknown = set(value) - set(_PROVIDER_FIELDS)
            if unknown:
                raise ValueError(
                    f'provider {name}: unknown fields {sorted(unknown)}')
            existing = _as_table(providers.get(name))
            merged = dict(existing)
            for field, v in value.items():
                if field == 'api_key' and v == SECRET_MASK:
                    continue
                if v is None or v == '':
                    merged.pop(field, None)
                else:
                    merged[field] = v
            if merged:
                providers[name] = merged
            else:
                providers.pop(name, None)
        else:
            raise ValueError(f'provider {name}: expected string, table or null')

    if providers:
        raw['providers'] = providers
    else:
        raw.pop('providers', None)

    import tomli_w

    tmp = config_path.with_suffix('.toml.tmp')
    tmp.write_text(tomli_w.dumps(raw), encoding='utf-8')
    tmp.replace(config_path)
    _sync_env_keys(set(patch), old_providers, providers)
    return {name: bool(providers.get(name)) for name in sorted(set(patch))}


def _as_table(entry) -> dict:
    """Normalize a stored provider entry (string shorthand or table) to a dict."""
    if isinstance(entry, dict):
        return {k: v for k, v in entry.items() if k in _PROVIDER_FIELDS}
    if isinstance(entry, str) and entry:
        return {'api_key': entry}
    return {}


def _set_provider_key(providers: dict, name: str, value: str) -> None:
    table = _as_table(providers.get(name))
    table['api_key'] = value
    providers[name] = table if len(table) > 1 else value  # keep shorthand form


def _clear_provider_key(providers: dict, name: str) -> None:
    table = _as_table(providers.get(name))
    table.pop('api_key', None)
    if table:
        providers[name] = table  # keep the definition, drop the key
    else:
        providers.pop(name, None)


# Default smoke endpoints for the built-in trio (custom providers must
# declare base_url to be testable).
_LEGACY_SMOKE_URLS = {
    'zai': 'https://api.z.ai/api/paas/v4',
    'deepseek': 'https://api.deepseek.com/v1',
}


def verify_provider_keys(
    config: Config, timeout_s: float = 8.0, transport=None,
) -> dict[str, dict]:
    """Auth smoke: one minimal request per configured provider.

    Catches a clobbered/placeholder key in the Settings tab instead of at the
    next run. `transport` is injectable for tests (default: http.client).
    Returns {provider: {'configured', 'ok', 'status', 'detail'}} — no secrets.

    #212: providers are user-defined. Each entry is tested against its
    base_url (or the built-in default endpoint for the legacy trio); a
    provider with no known endpoint is reported configured but untested.
    """
    from urllib.parse import urlsplit

    def _http(url: str, headers: dict, body: dict | None) -> tuple[int, str]:
        import http.client
        import json as _json

        parts = urlsplit(url)
        host = parts.hostname or ''
        loopback = host in ('localhost', '127.0.0.1', '::1')
        if parts.scheme not in ('https', 'http'):
            return 0, f'unsupported url scheme: {parts.scheme!r}'
        if parts.scheme == 'http' and not loopback:
            # Local OpenAI-compatible endpoints (Ollama, LM Studio) are the
            # common http case; anything else must be https.
            return 0, 'non-https url rejected (http allowed only on localhost)'
        payload = _json.dumps(body).encode() if body is not None else None
        conn_cls = (
            http.client.HTTPSConnection if parts.scheme == 'https'
            else http.client.HTTPConnection)
        conn = conn_cls(parts.netloc, timeout=timeout_s)
        path = parts.path or '/'
        try:
            conn.request('POST' if payload is not None else 'GET', path,
                         body=payload, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.read(300).decode('utf-8', 'replace')
        except OSError as exc:
            return 0, str(exc)
        finally:
            conn.close()

    send = transport or _http

    def _chat(base_url: str, key: str) -> tuple[int, str]:
        return send(base_url.rstrip('/') + '/chat/completions', {
            'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
        }, {'model': 'smoke', 'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 1, 'stream': False})

    def _result(name: str, key: str | None) -> dict:
        if not key:
            return {'configured': False, 'ok': False, 'status': None,
                    'detail': 'no key'}
        d = config.providers.get(name, ProviderDef())
        base = d.base_url
        if name == 'zai' and not d.base_url:
            base = config.models.fallback_base_url or _LEGACY_SMOKE_URLS['zai']
        base = base or _LEGACY_SMOKE_URLS.get(name)
        if name == 'github' and not d.base_url:
            status, detail = send('https://api.github.com/user',
                                  {'Authorization': f'Bearer {key}'}, None)
            return {'configured': True, 'ok': status == 200, 'status': status,
                    'detail': None if status == 200 else detail[:200]}
        if not base:
            return {'configured': True, 'ok': None, 'status': None,
                    'detail': 'no base_url configured — not tested'}
        status, detail = _chat(base, key)
        # 400/404 = auth passed but the smoke model name isn't on the plan.
        ok = status in (200, 400, 404)
        return {'configured': True, 'ok': ok, 'status': status,
                'detail': None if ok else detail[:200]}

    # Configured providers, plus legacy ones whose env key alone is set.
    names = dict(config.providers)
    env = os.environ
    for legacy, env_name in _LEGACY_ENV_VARS.items():
        if legacy not in names and env.get(env_name):
            names[legacy] = ProviderDef()
    return {name: _result(name, provider_effective_key(name, d))
            for name, d in sorted(names.items())}


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
    except FileNotFoundError:
        raw = {}
    except tomllib.TOMLDecodeError as exc:
        # Writing from an empty dict here once replaced the user's ENTIRE
        # config — provider API keys included — with a models-only file.
        raise ValueError(
            f'existing config.toml is not valid TOML ({exc}); '
            'refusing to overwrite it — fix or remove the file first'
        ) from exc

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
class ProviderDef:
    """One user-defined provider (#212): an OpenAI-compatible endpoint.

    `api_key` is the config-stored key (env var wins at resolution time —
    see provider_effective_key); `base_url` routes `name:model` bindings to
    this endpoint; `env_var` overrides the default <NAME>_API_KEY name.
    """
    api_key: str | None = None
    base_url: str | None = None
    env_var: str | None = None


def provider_env_var(name: str) -> str:
    """Env var holding this provider's key: legacy names for the built-in
    trio, <NAME>_API_KEY (sanitized) for user-defined providers."""
    if name in _LEGACY_ENV_VARS:
        return _LEGACY_ENV_VARS[name]
    sanitized = re.sub(r'[^A-Z0-9]+', '_', name.upper()).strip('_')
    return f'{sanitized}_API_KEY'


def provider_effective_key(name: str, d: ProviderDef) -> str | None:
    """The key actually used: env var wins over the stored value."""
    return os.environ.get(d.env_var or provider_env_var(name)) or d.api_key


@dataclass(frozen=True)
class Config:
    """Top-level CodingDude configuration assembled from config home + environment."""
    models: ModelLineup
    shell: ShellConfig
    providers: dict[str, ProviderDef] = field(default_factory=dict)
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
            providers={},
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
        providers=_parse_providers(providers),
        delegation=delegation,
    )
    apply_provider_keys(config)
    return config


def _parse_providers(raw: dict) -> dict[str, ProviderDef]:
    """[providers] table -> ProviderDef map (#212).

    Accepts the legacy string shorthand (`zai = "key"`) and full tables
    (`[providers.openrouter] api_key/base_url/env_var`).
    """
    out: dict[str, ProviderDef] = {}
    for name, value in (raw or {}).items():
        if isinstance(value, str):
            if value:
                out[name] = ProviderDef(api_key=value)
        elif isinstance(value, dict):
            out[name] = ProviderDef(
                api_key=value.get('api_key'),
                base_url=value.get('base_url'),
                env_var=value.get('env_var'),
            )
        else:
            logging.getLogger(__name__).warning(
                'config.toml [providers].%s: unsupported shape %s; ignored',
                name, type(value).__name__)
    return out


def apply_provider_keys(config: Config) -> None:
    """Config-stored keys are the low-precedence fallback; env vars win."""
    for name, d in config.providers.items():
        if d.api_key:
            os.environ.setdefault(d.env_var or provider_env_var(name), d.api_key)


def load_project_config(workdir: Path) -> dict:
    """Per-project overrides from `.codingdude.toml` in the Workdir.

    Currently: shell (str or table) and the `[models]` table (#210). The
    models dict is returned raw — validation lives in
    apply_project_models, which merges it over the global lineup.
    """
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
    models = raw.get('models')
    if isinstance(models, dict):
        out['models'] = models
    return out


def apply_project_models(config: Config, workdir: Path) -> Config:
    """Overlay the project's `[models]` overrides onto the global lineup (#210).

    Field-wise merge: only keys present in `.codingdude.toml` win; everything
    else keeps the global config.toml value. The merged result is validated
    (ModelLineupIn) before use — an invalid project override logs a warning
    and leaves the global lineup in place, mirroring load_config's
    fail-safe handling of a broken global config.toml.
    """
    project_models = load_project_config(workdir).get('models')
    if not project_models:
        return config
    unknown = set(project_models) - set(ModelLineupIn.model_fields)
    if unknown:
        logging.getLogger(__name__).warning(
            'project .codingdude.toml [models]: unknown keys %s ignored',
            sorted(unknown))
        project_models = {
            k: v for k, v in project_models.items() if k in ModelLineupIn.model_fields}
    if not project_models:
        return config
    current = {
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
    }
    merged = {k: v for k, v in {**current, **project_models}.items() if v is not None}
    try:
        validated = ModelLineupIn(**merged)
    except ValidationError as exc:
        logging.getLogger(__name__).warning(
            'project .codingdude.toml [models] invalid (%s); using global lineup', exc)
        return config
    new_models = ModelLineup(
        main=validated.main,
        subagent=validated.subagent,
        fallback=validated.fallback,
        fallback_base_url=validated.fallback_base_url,
        vision=validated.vision,
        thinking=validated.thinking,
        max_tokens=validated.max_tokens,
        context_limit=validated.context_limit,
        request_limit=validated.request_limit,
        pricing=validated.pricing,
    )
    return replace(config, models=new_models)
