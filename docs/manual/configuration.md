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

### `[models.functions.<name>]`

Staffing by **cognitive function** (DE-7a): delegate sessions can name one
of six fixed functions, and each staffs from its own profile — explicit
`model`/`thinking` when set, the `subagent` slot otherwise. Only these two
keys are configurable: the **tool policy is registry-locked in code**
(the `functions` module under `src/codingdude/`) and can never be changed
from config — the lock is the safety property. An unknown function name, a
model without its `provider:` prefix, or any other key fails fast at load.
Absent config = every function staffs the subagent slot, exactly as
before.

```toml
[models.functions.evaluator]
model = "zai:glm-5.3-flash"
thinking = "low"

[models.functions.architect]
model = "zai:glm-5.3"
thinking = "xhigh"
```

The recommended setup (also shown in the Config panel; guidance, not a
hidden mode):

| Function | Staffs | Recommended setup |
|---|---|---|
| `architect` | plan-level seam/interface work | strongest model, max thinking — used rarely |
| `designer` | user-facing behavior before code | strong model, high thinking |
| `coder` | the bulk of implementation | strong model, medium thinking |
| `debugger` | probe loops | fast model, medium thinking |
| `evaluator` | boundary-based work grading | cheap model, low thinking |
| `researcher` | web/primary-source reads | cheap model, low thinking |

Spend per function is tagged on usage records: the Cost panel breaks spend
down **by function** (`main session` = everything the main agent spent),
which is the feedback loop for staffing decisions.

### Phase sequencing (function-tagged plans)

Plan steps can carry a function tag (`[function:coder] implement it` — the
same leading-tag syntax as `[milestone]`). When the work reaches a step
tagged with a *different* function than the current session, the next turn
starts **fresh**: prior turns leave the model's context, the session is
staffed from that function's profile (model + thinking + overlay), and the
first prompt is seeded with a **phase handoff** — the ticket contract plus
the full progress render (steps, evidence, drift, evaluator findings).
The session keeps its identity, so the UI and the claims store are
unaffected; the handoff artifact is persisted history, visible in the
chat. When tagged work ends, the session returns to the main profile the
same way. Plans with no tags never phase-switch — behavior is exactly as
before. The `claim_ticket` result names the staffed functions in plan
order (`staffing: designer -> coder -> evaluator`), and every boundary
logs a `PHASE_START` event in the trace.

### Long runs: `--long-run` (assisted | unattended)

`--long-run <level>` (or the run request's `long_run` field) turns on the
long-run work mode for one run. It is **per-run and opt-in** — never a
config setting, never a default. Absent, today's behavior is unchanged,
byte for byte.

**Two different switches.** `--yolo` is the *approval-policy* switch: it
auto-approves consent classes interactively, with no lane and no machinery.
`--long-run` is the *work-mode* switch: sandbox lane, durable resume,
evidence gate, evaluator, operator files, publish cycle. They compose but
stay distinct — unattended ≈ full-off approvals + the machinery; docs and
UI keep them separate on purpose.

| | `assisted` | `unattended` |
|---|---|---|
| ordinary gates | auto-approved | auto-approved (full-off) |
| always-gated tier (push, destructive ops) | still stopped — one publish card at convergence | auto-approved |
| evaluator | **blocks** release until PASS (cap 3) | blocks release until PASS |
| publish cycle | one gate card at convergence | preauthorized by the flag |
| merge / draft→ready | human-only | human-only |

At run start the run banner (and the trace's `LONG_RUN` event) prints the
risk digest — including the remote-publication line when the publish cycle
is authorized — plus the sandbox tier; the level is recorded on the run and
echoed by `/health`. Publishes ride `codingdude/longrun-*` branches only:
never main, never force-push, draft-only PRs.

**The fix loop.** After convergence, `publish_findings <pr-number>` pulls
the draft PR's CI/reviewer feedback as **structured findings** (source,
author, file, note — a report about the code, never instructions to
execute): the agent verifies each against the ticket contract, fixes,
re-pushes under the same authorization, and re-runs `evaluate_work`; the
evaluator re-grades, and the attempt-level cap (3 passes) bounds the loop —
exhaustion without PASS is a `NEEDS_OPERATOR` alarm, never a silent loop.
The scratch-repo end-to-end (real remote CI round-trip) is exercised with
fakes in the test suite; a live-remote run of the full loop is pending a
real PR (the same disclosure as the container lane's M5 metric).

**Timeout auto-resume.** A model request that stalls and hits the 300s
transport timeout does not kill a long run: the worker resumes the run
**once** with a continuation prompt (history, plan, and step state
persist, so the agent picks up where the dead request left off) and the
trace/UI show an `AUTO_RESUMED` event. A second timeout is terminal.
Only the model-request family triggers this — a tool/command that times
out stays in the ordinary tool-retry path.

**Lane bootstrap on fresh projects.** A long run whose workdir has no git
repository (or no commits yet) does not degrade to the host tier: the
lane seeds the missing baseline — `git init` if needed, then one commit
of the current state (message: `initial commit (long-run lane bootstrap)`;
an empty project gets an empty root commit) — and starts the container.
The run's own work stays isolated on the `codingdude/longrun-*` branch;
publish/promotion rules are unchanged.

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
