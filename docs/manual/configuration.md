# Configuration

Up: [User Manual](../USER-MANUAL.md) · Next: [Extending](extending.md)

Everything user-level lives in `~/.codingdude/` (override with the
`CODEDUDE_HOME` environment variable). The main file is `config.toml`,
created with defaults on first use. You can edit it by hand or use the
**Config** panel — the panel edits the same file. Either way, changes apply
from the **next run**; no server restart is needed.

Model names are always `provider:model` (e.g. `zai:glm-5.3`). The provider
is either a built-in (`deepseek`, `zai`, `openai`, `anthropic`, `google`,
`github`, `groq`, `mistral`, `ollama`, `bedrock`) or any name you define
under `[providers.<name>]`.

## Worked examples

### 1. DeepSeek (the default)

What first boot writes — just add keys:

```toml
[models]
main = "deepseek:deepseek-v4-pro"
subagent = "deepseek:deepseek-v4-flash"
fallback = "zai:glm-5.3"
```

Keys: `DEEPSEEK_API_KEY` and `ZAI_API_KEY` in the environment, or stored
under `[providers]` (below). PowerShell: `$env:DEEPSEEK_API_KEY = "..."`;
bash: `export DEEPSEEK_API_KEY=...`.

### 2. Z.AI GLM coding plan

Coding-plan subscription keys are **rejected by the standard Z.AI API** —
they only work against the coding-plan endpoint:

```toml
[models]
main = "zai:glm-5.3"
subagent = "zai:glm-5.3-flash"
fallback = "zai:glm-5.3-flash"
fallback_base_url = "https://api.z.ai/api/coding/paas/v4"
# cost lever on GLM models: minimal | low | medium | high | xhigh | off
thinking = "low"
```

Despite the name, `fallback_base_url` routes **every** `zai:` binding
(`main`, `subagent` and `fallback`) to that endpoint — so one coding-plan
key works everywhere. If `fallback` is a `zai:` model and
`fallback_base_url` is unset, the Config panel warns you; the key
verification smoke test also uses the endpoint.

### 3. A custom OpenAI-compatible provider (OpenRouter)

```toml
[providers.openrouter]
api_key = "sk-or-..."
base_url = "https://openrouter.ai/api/v1"
# env_var = "OPENROUTER_API_KEY"   # default is <NAME>_API_KEY

[models]
main = "openrouter:anthropic/claude-sonnet-4"
subagent = "openrouter:anthropic/claude-haiku-4"
```

A provider with a `base_url` routes every `name:model` binding to that
endpoint. Without a `base_url`, built-in provider names resolve through
their native support.

### 4. A local model (Ollama, LM Studio)

```toml
[providers.ollama]
base_url = "http://localhost:11434/v1"
api_key = "local"   # local servers ignore it, but the OpenAI client needs a value

[models]
main = "ollama:qwen3-coder"
```

`http://` base URLs are accepted for localhost endpoints only; remote
endpoints must be `https://`.

## API keys: precedence and storage

- **Environment wins.** A provider's effective key is its env var if set,
  otherwise the stored `api_key`.
- Env var names: `ZAI_API_KEY`, `DEEPSEEK_API_KEY`, `GITHUB_PAT` (historical
  built-ins); custom providers default to `<NAME>_API_KEY` (e.g.
  `OPENROUTER_API_KEY`), overridable with `env_var`.
- Storing a key in `config.toml` is convenient (it is `setdefault`-ed into
  the environment at load); it is displayed back only as *presence*, never
  as text, in the UI and API.
- **Verify keys** in the Config panel sends one minimal request per
  provider. For GitHub it checks `api.github.com/user`; for chat providers
  any of HTTP 200/400/404 counts as *authenticated* (a 400 just means the
  smoke model name isn't on your plan).

## Full reference

### `[models]`

| Key | Default | Purpose |
|---|---|---|
| `main` | `deepseek:deepseek-v4-pro` | primary agent loop |
| `subagent` | `deepseek:deepseek-v4-flash` | delegated sub-agents |
| `fallback` | `zai:glm-5.3` | automatic failover when the main model errors |
| `fallback_base_url` | *(unset)* | endpoint override — see example 2; applies to all `zai:` bindings |
| `vision` | *(unset)* | vision-capable model for image input; unset disables image input |
| `thinking` | *(unset)* | reasoning depth for models that support it: `minimal`–`xhigh`, or `off` |
| `max_tokens` | provider default | max response tokens — raise if responses get truncated |
| `context_limit` | inferred from model name | context-window override; drives compaction timing and the sidebar meter |
| `request_limit` | `500` | max model requests per run (the library default of 50 is too low for agentic sessions) |
| `pricing` | *(unset)* | cost rates — see [pricing](#pricing) |

### `[providers.<name>]`

| Key | Purpose |
|---|---|
| `api_key` | key stored in config (env var wins) |
| `base_url` | OpenAI-compatible endpoint; routes all `<name>:model` bindings here |
| `env_var` | override the default `<NAME>_API_KEY` env var name |

The legacy shorthand `[providers] zai = "key"` (a bare string) still works
and is preserved by the UI when you edit other fields.

### `[shell]`, `[delegation]`, `[planning]`

```toml
[shell]
default = "bash"        # or "powershell"

[delegation]            # per-`delegate`-call ceilings for sub-agents
max_requests = 40
# max_cost_usd = 1.00   # unset = no cost ceiling

[planning]
github_mirror = true    # mirror tickets/roadmap items to GitHub issues via gh
                        # (best-effort; needs a github.com origin + gh auth)
```

## Per-project overrides: `.codingdude.toml`

A `.codingdude.toml` in the project workdir overrides the global config for
sessions in that project. Currently supported: `shell`, a `[models]`
overlay, and `[kickoff]` prompts. The models overlay is a **field-wise
merge** — only keys you set win — and it is validated; an invalid override
logs a warning and the global lineup is used unchanged.

```toml
# myproject/.codingdude.toml
shell = "powershell"

[models]
main = "openrouter:anthropic/claude-sonnet-4"   # this project only

[kickoff]
existing = """
Our pipeline: plan first, open a GitHub issue, implement, run
`uv run pytest -q` plus ruff and mypy, then request review.
Never push without an explicit "push" from me.
"""
```

### Kickoff prompts

Every new session's **first turn** rides an executed *kickoff*: an
orientation block the agent acts on before handling your request. The
variant is chosen automatically — `existing` when the workdir holds a
project (read HANDOFF / ROADMAP / CONTEXT, re-anchor the pipeline
contract) or `new` when it is greenfield (interview you about purpose,
stack, and tracking before scaffolding anything). Later turns carry only
your words; the kickoff fires once per session.

Override the bundled text per project with `[kickoff] existing` /
`[kickoff] new` (above); omitted keys fall back to the versioned prompts
shipped in `src/codingdude/prompts/kickoff-*.md`. Kickoff text must not
contain a bare `---` line — that separator is how the block is joined to
your message and later stripped, so one inside the text ends the block
early.

## Pricing

`pricing` maps a model name-or-substring to USD per **1M tokens**; unpriced
models are accounted tokens-only in the Cost panel:

```toml
[models]
pricing = { deepseek-v4-pro = { input = 0.27, output = 1.1 } }
```

Substring matching means one entry can cover a model family (e.g. key
`glm-5` matches `glm-5.3` and `glm-5.3-flash`).

## The Config panel's save semantics

Worth knowing because it prevents accidents:

- Saving the lineup is a **merge**: only fields you changed are written; an
  explicit clear is required to empty one. A partial save can never wipe
  `fallback_base_url` (the classic way to silently break a coding-plan key).
- Stored keys round-trip as a sentinel ("set"); saving the panel verbatim
  cannot overwrite a real key with the placeholder.
- A payload that fails validation is rejected before any write — a bad save
  cannot brick the next boot.

Next: [Extending](extending.md)
