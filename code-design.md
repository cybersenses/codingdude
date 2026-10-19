# Code Design Notes

## #212 — user-defined providers (any OpenAI-compatible endpoint)

**Problem:** provider names were hardcoded (deepseek/zai/github) in config,
API, verification, and UI; users could not add providers or select between
them at runtime.

**Design:**
- `ProviderDef` (config.py): `{api_key?, base_url?, env_var?}`; stored as
  `[providers.<name>]` tables in config.toml; legacy string shorthand kept.
- Key resolution: `provider_effective_key(name, def)` — env var
  (`env_var` or legacy name or `<NAME>_API_KEY`) wins over stored `api_key`;
  `apply_provider_keys` setdefaults it into the environment at load.
- Model resolution (`engine._model_from_name(name, base_url, providers)`):
  1) prefix matches a provider def with `base_url` → `OpenAIChatModel` on
     `AsyncOpenAI(base_url)` (works for any OpenAI-compatible API);
  2) `zai:` + `fallback_base_url` → dedicated ZaiModel (coding-plan endpoint);
  3) else pydantic-ai `infer_model` (all native providers).
- Validation relaxed: any `x:y` model ref is accepted (ModelLineupIn).
- API: `models_payload` adds `provider_defs` (base_url/env_var, no secrets)
  and `provider_prefixes` (suggestion list); `save_provider_keys` accepts
  per-entry string (key), table (full def merge), or null (delete);
  SECRET_MASK sentinel contract unchanged. `/models` also returns
  `provider_prefixes` for the run composer.
- Verify: generic per-provider smoke against its base_url; legacy trio keep
  default endpoints; no-base_url providers report `ok: null` "not tested".
- UI: Config tab renders dynamic provider rows (key/base_url/env_var,
  clear/remove) + add row; lineup fields get a provider-prefix datalist;
  run composer model selector now sends real `provider:model` strings
  (previously sent slot names, which never resolved).

**Impact:** config.py, engine.py, worker.py, server.py, App.jsx, README.
Config loads per run — provider changes apply from the next run, no bounce.

**Fail-safe:** unknown provider-table shapes warn+skip; bad PUT payloads are
validated before any write; `provider_effective_key` falls back to
`'not-set'` key so construction errors surface at run time, not boot.
