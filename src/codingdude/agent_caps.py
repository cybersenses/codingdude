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
"""Prompt-caching capability profiles for every agent (R91 #338).

One resolution point turns the `[models]` cache config into pydantic-ai
capabilities, so an agent cannot silently ship without caching. Two profiles:

- `RUN`: the main run agent and its fix-loop retries. One long, growing
  conversation read again on every turn — cache the conversation, plus a
  retention the operator can set.
- `ONE_SHOT`: grader / reviewer / summariser / extractor / auditor / delegate
  / vision. Each call sends a *different* conversation with the *same* long
  instruction block, so caching the conversation writes a breakpoint no
  request ever reads (a 1.25x write for nothing). Retention only.

Retention matters more than the write multiplier for us: our own `ask_user`
timeout is 1800 s, six times Anthropic's 5-minute tier, so the provider
default can expire mid-session and re-write the whole prefix. `'1h'` is the
default where the provider has that tier; `snap_cache_retention` degrades an
unsupported tier to the nearest shorter one, and a provider with no retention
tiers at all falls back to its own default (implicit-cache models such as
DeepSeek and GLM ignore the setting entirely, which is the correct no-op).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import KW_ONLY, dataclass, field
from typing import Any, Literal, cast

from pydantic_ai.capabilities import AbstractCapability, Caching
from pydantic_ai.settings import ModelSettings

logger = logging.getLogger(__name__)

CacheRetention = Literal['5m', '30m', '1h', '12h']
CacheSpec = bool | CacheRetention

#: Retention tiers pydantic-ai understands, shortest first.
CACHE_RETENTIONS: tuple[CacheRetention, ...] = ('5m', '30m', '1h', '12h')

#: Default retention. Outlives our 1800 s ask timeout on providers that have
#: an hour tier; providers without tiers fall back to their own default.
DEFAULT_CACHE_RETENTION: CacheSpec = '1h'

#: Agent profiles. The profile decides whether the growing conversation is
#: cached, not whether caching happens at all.
RUN = 'run'
ONE_SHOT = 'one_shot'

#: Provider-specific cache settings that take precedence over the unified
#: `cache` field for their provider (pydantic_ai.settings.ModelSettings doc,
#: 2.66.0). Mirrored here so a typo in config.toml fails at load with a
#: readable message instead of being dropped by the provider translation.
PROVIDER_CACHE_SETTINGS: frozenset[str] = frozenset({
    # Anthropic (native client)
    'anthropic_cache',
    'anthropic_cache_instructions',
    'anthropic_cache_tool_definitions',
    'anthropic_cache_messages',
    # Bedrock (Anthropic and Amazon Nova models only)
    'bedrock_cache_instructions',
    'bedrock_cache_tool_definitions',
    'bedrock_cache_messages',
    # OpenRouter (Anthropic and Gemini models only)
    'openrouter_cache_instructions',
    'openrouter_cache_tool_definitions',
    'openrouter_cache_messages',
    # OpenAI (GPT-5.6+ on the OpenAI and Azure OpenAI v1 APIs)
    'openai_prompt_cache_options',
    'openai_cache_instructions',
    'openai_prompt_cache_retention',
})


def parse_cache_retention(value: object, *, where: str = 'prompt_cache') -> CacheSpec:
    """Validate a `prompt_cache` config value.

    Accepts `True`, `False`, or a retention tier. Raises `ValueError` so a
    hand-edited config fails at load, not mid-run when pydantic-ai's own
    `snap_cache_retention` would raise on the first model request.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value in CACHE_RETENTIONS:
        return value  # type: ignore[return-value]  # membership-checked above
    raise ValueError(
        f'{where}: expected true, false, or one of '
        f'{", ".join(repr(tier) for tier in CACHE_RETENTIONS)}; got {value!r}'
    )


def validate_cache_settings(value: object) -> dict[str, Any]:
    """Validate the provider passthrough map (`prompt_cache_settings`).

    Unknown keys are rejected: pydantic-ai ignores cache settings it does not
    know, so a typo would otherwise be a silent no-op that looks configured.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(
            f'prompt_cache_settings: expected a table of provider cache '
            f'settings; got {value!r}'
        )
    unknown = sorted(str(key) for key in value if key not in PROVIDER_CACHE_SETTINGS)
    if unknown:
        raise ValueError(
            'prompt_cache_settings: unknown key(s) '
            + ', '.join(repr(key) for key in unknown)
            + '. Use one of '
            + ', '.join(repr(key) for key in sorted(PROVIDER_CACHE_SETTINGS))
            + '.'
        )
    return dict(value)


@dataclass
class ProviderCacheSettings(AbstractCapability[Any]):
    """Provider-specific cache settings carried as a capability.

    Capabilities contribute model settings per request (the combined
    capability merges them on top of the agent's own settings), which is what
    lets one seam reach every agent without threading a settings merge
    through eight call sites. Values take precedence over the unified `cache`
    field for their provider, exactly as pydantic-ai documents.
    """

    _: KW_ONLY

    settings: Mapping[str, Any] = field(default_factory=dict)

    id: str | None = 'provider_cache_settings'
    """Fixed id: an agent has one provider cache configuration, so two of
    them resolve to one via `combine` (which keeps the last), like `Caching`."""

    def get_model_settings(self) -> ModelSettings | None:
        if not self.settings:
            return None
        # TypedDict at type level, plain dict at runtime: the keys are the
        # provider-specific settings this module validates at load.
        return cast(ModelSettings, dict(self.settings))


def cache_capabilities(models: Any, profile: str = RUN) -> list:
    """Capabilities carrying the cache configuration for one agent.

    `models` is the resolved `config.ModelLineup` (or any object exposing
    `prompt_cache`, `prompt_cache_messages`, `prompt_cache_settings`); `None`
    means "no configuration available" and yields no capabilities.

    `prompt_cache = false` disables library-managed caching but still honours
    an explicit `prompt_cache_settings` map: that is a deliberate opt-in to a
    provider's own knobs, not the same intent as "no caching".
    """
    if models is None:
        return []
    caps: list = []
    spec = parse_cache_retention(
        getattr(models, 'prompt_cache', True), where='prompt_cache'
    )
    if spec is not False:
        messages = False if profile == ONE_SHOT else bool(
            getattr(models, 'prompt_cache_messages', True)
        )
        caps.append(Caching(retention=spec, messages=messages))
    passthrough = validate_cache_settings(
        getattr(models, 'prompt_cache_settings', None)
    )
    if passthrough:
        caps.append(ProviderCacheSettings(settings=passthrough))
    return caps
