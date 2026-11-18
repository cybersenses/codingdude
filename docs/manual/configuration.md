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

In the Settings tab's model lineup, **Fetch model list** queries each
configured OpenAI-compatible provider live and turns its model ids into
datalist suggestions (`provider:model-id`), so you can pick instead of
typing from memory. Native providers (anthropic, google) have no
OpenAI-compatible listing endpoint — their fields stay free-text. The
fetch is read-only; typing a literal id always still works.

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
| `compact_per_request` | `true` | mechanical, model-free compaction before every request while a run is live; `false` restores run-start-only compaction |
| `prompt_cache` | `"1h"` | prompt caching for every agent: `true`, `false`, or a retention tier — see [Prompt caching](#prompt-caching) |
| `prompt_cache_messages` | `true` | also cache the growing conversation (main loop only; one-shot agents never do) |
| `prompt_cache_settings` | `{}` | provider-specific cache settings; takes precedence over `prompt_cache` for that provider |
| `request_limit` | `500` | max model requests per run (the library default of 50 is too low for agentic sessions) |
| `max_cost_usd` | *(unset)* | hard USD ceiling applied to **each `agent.run()`** in a run — see [Run ceilings](#run-ceilings) |
| `max_total_tokens` | *(unset)* | hard token ceiling applied to **each `agent.run()`** in a run |
| `pricing` | *(unset)* | cost rates — see [pricing](#pricing) |

### Run ceilings

`request_limit` was the only thing ever bounded. A single enormous request, or a
long run of large ones, was unbounded in tokens and in money. `max_cost_usd` and
`max_total_tokens` are hard stops: pydantic-ai checks them *before* the next
request and raises, so the call is refused rather than narrated afterwards. They
apply to **every `agent.run()` inside the run** — the main loop, the fix loop, the
claims retry, the evaluator, the planning reviewer, the summariser, memory
extraction, the claims auditor and the vision inspector — not just the main loop. Both are unset by
default, so an unconfigured install behaves exactly as before. The Config panel
carries both keys through a save unchanged, but has no input for them yet — set
them in `config.toml`.

**Read these as a per-call ceiling, not a run total.** Each `agent.run()` gets
its own allowance, because the auxiliary agents do not share the main loop's usage
accumulator: with `max_cost_usd = 2`, one run may legitimately spend up to about
$2 per call site rather than $2 in total. The cumulative figure — the one that
answers "what did this session cost" — is the ledger (`db.session_usage`), and
the mechanism that stops spend against it is `--budget` (the Budget Cap). Use the
ceilings to stop any single call running away, and the Budget Cap to bound the
session.

**Honest ceiling:** `max_cost_usd` can only be enforced when pydantic-ai can
price the model in use. On an unpriced provider the boundary check silently
cannot fire, and pydantic-ai's `UsageLimits.check_cost` emits
`CostNotFoundWarning` to say so — it will not protect you there.
`max_total_tokens` needs no pricing, so it is the ceiling that always holds. Set
both on a priced model; always set the token one.

Which ceiling owns what:

| Where | Scope | Mechanism |
|---|---|---|
| `[models] max_cost_usd` / `max_total_tokens` | one `agent.run()` | `UsageLimits`, checked before each request |
| `[delegation] max_cost_usd` / `max_requests` | one `delegate` call | a *slice* of the run's spend, same mechanism |
| `--budget` (Budget Cap) | whole session | the usage ledger in the database, across runs |

They do not disagree: the session cap is the ledger total, the per-`agent.run()`
cap is where a call is actually refused, and a delegation gets the remainder it may
reach. A malformed value in either `[models]` ceiling fails loudly at load rather
than silently becoming no cap.

### Prompt caching

Caching is resolved in one place for **every** agent, not just the main loop,
and the two families are treated differently on purpose:

- **The main loop** (and its fix-loop and claims retries) reads one long,
  growing conversation on every turn — so the conversation is worth caching as
  well as the instruction prefix.
- **One-shot agents** (evaluator, reviewer, summariser, memory extractor,
  claims auditor, delegate, vision) each send a *different* conversation with
  the *same* long instruction block. Caching the conversation there writes a
  breakpoint no request ever reads, so only the prefix is cached.

`prompt_cache` accepts `true`, `false`, or `"5m"`, `"30m"`, `"1h"`, `"12h"`.
The default is `"1h"` rather than a provider's five-minute tier because a
session can sit on an `ask_user` card for up to 1800 s — longer than the short
tier survives, which would make the next turn re-write the whole prefix.
Tiers a provider does not offer degrade to the nearest shorter one it has, and
providers with no tiers at all (implicit-cache models such as DeepSeek and GLM)
ignore the setting: a correct no-op, not a misconfiguration.

`prompt_cache = false` turns off library-managed caching but still honours an
explicit `prompt_cache_settings` map — that map is a deliberate opt-in to a
provider's own knobs. Its keys are validated at load (`anthropic_cache_*`,
`bedrock_cache_*`, `openrouter_cache_*`, `openai_prompt_cache_options`,
`openai_cache_instructions`, `openai_prompt_cache_retention`), so a typo fails
at boot instead of becoming a silent no-op:

```toml
[models]
prompt_cache = "1h"
prompt_cache_messages = true
prompt_cache_settings = { anthropic_cache_instructions = true }
```

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

[delegation]            # how much MORE one `delegate` call may spend
max_requests = 40
# max_cost_usd = 1.00   # unset = no cost ceiling (a ceiling, enforced, not a note)

[planning]
github_mirror = true    # mirror tickets/roadmap items to GitHub issues via gh
                        # (best-effort; needs a github.com origin + gh auth)
```

`max_requests` is a **slice, not a budget of its own**: a delegation may spend
`max_requests` requests *beyond* what the session already spent, and never more
than `[models] request_limit` allows overall. `max_cost_usd` works the same way:
it is the delegation's own allowance *beyond* what the session already spent, so
it is a ceiling, not a receipt — the call is refused before the money goes out,
and the abort message names the limit that fired. Delegated requests and tokens
count against the run that caused them — they appear in the run's usage and its
limits.

### `[trace]`

```toml
[trace]
deltas = "compact"      # or "full" — compact coalesces streaming text deltas
                        # into one line per flush window, which keeps long
                        # traces small; "full" keeps every delta separately
```

The JSONL trace per session is what the Trace panel replays and what an
evidence check reads back. `compact` is the default: a long run otherwise
writes one line per token delta.

### `[telemetry]`

OpenTelemetry spans for agent runs, exported to a **local** collector.

```toml
[telemetry]
enabled = false                            # off by default
otlp_endpoint = "http://127.0.0.1:4318"    # any local OTLP/HTTP collector
service_name = "codingdude"
```

This is the other kind of trace, and it answers a different question. The
`[trace]` JSONL above records what happened in a session for replay and
evidence; `[telemetry]` emits one span per model request and per tool call, so
a slow or failing run can be read as a timeline: which agent, which request,
how many tokens, how long.

- **Local only.** `send_to_logfire=False`: no token, no account, nothing leaves
  the machine. Run prompts contain your code, so this is a constraint, not a
  default to relax.
- **Off by default, and never fatal.** Every malformed value — the boolean as
  much as the endpoint — is logged once and turns tracing off. Tracing never
  stops a run or a worker: `enabled = "false"` (quoted, so not a TOML boolean)
  leaves it off; `otlp_endpoint = "4318"` (no scheme) falls back to the default
  listener; an unreachable collector just produces no traces.
- Any OTLP/HTTP collector works: Grafana Agent, Jaeger (`:4318`), an
  OpenTelemetry Collector, or `logfire` served locally. Point
  `otlp_endpoint` at it and set `enabled = true`.
- Everything is named: `main`, `fix-loop`, `claims-retry`, `claims-auditor`,
  `compaction`, `memory-extraction`, `evaluator`, `planning-reviewer`,
  `vision-inspector`, and each delegation as `delegate.<function>`
  (`delegate.designer`, `delegate.coder`, …; plain `delegate` when no function
  was requested). Filter spans by agent name to see where the time or the
  tokens actually went.
- `[telemetry]` is **global only** — it lives in `~/.codingdude/config.toml`,
  not in a project `.codingdude.toml`, so one collector serves every project.

#### Viewing traces: a local collector

Traces have no UI of their own — this exports spans to a collector, and you
need one running. Two self-hosted options fit the local-only constraint
(Apache-2.0, no fee, no account): the **OTel Desktop Viewer** (one executable —
the option verified against our spans, below) and **OpenLIT** (Docker, whose
dashboard has not been verified against them).

**Enabling tracing needs your consent, every time.** It is off by default for a
reason: spans describe what your agent read and did, and the collector is
another process on your machine. Nothing is exported until you set
`enabled = true` yourself — no tool, agent or update will flip it for you. Leave
it off unless you intend to run a collector and read the traces.

##### OTel Desktop Viewer (one executable, no Docker)

[CtlSpice/otel-desktop-viewer](https://github.com/CtrlSpice/otel-desktop-viewer)
packages an OpenTelemetry Collector, a DuckDB store and a web UI into a single
executable. Its receivers already listen where this export points, so no
endpoint value needs changing.

1. Download the release archive for your platform (`otel-desktop-viewer_windows_amd64.zip`
   on Windows) and unzip it outside the repository — the binary is ~114 MB.
2. Run `otel-desktop-viewer.exe`. It starts receivers on `4317` (gRPC) and
   `4318` (HTTP) and serves the UI on <http://localhost:8000>; it opens a browser
   on launch (`--open-browser=false` stops that).
3. Set `enabled = true` as below. `otlp_endpoint` already holds the matching
   value.

Read traces at <http://localhost:8000/traces>. Storage is in memory by default;
`--db telemetry.duckdb` persists it to a file and `--db-max-size` caps its
growth (2 GB with a file, 512 MB in memory).

**Verified here** (2026-11-18, viewer v0.7.0): with `[telemetry]` enabled through
the shipped `tracing.configure_tracing` → `OTLPSpanExporter` at
`http://127.0.0.1:4318/v1/traces`, one real `deepseek-flash` request stored both
pydantic-ai spans — `invoke_agent agent` and `chat deepseek-flash` — with their
`gen_ai.*` attributes intact (43 input / 12 output tokens). So the span path
works end to end, not just "it should".

**That store is sensitive.** The spans carry `gen_ai.input.messages`,
`gen_ai.output.messages` and `gen_ai.system_instructions` — your prompts, the
agent's answers and the instructions — plus logfire's own cost estimate
(`operation.cost`). This is why the export is local-only and off by default.

The same binary queries the running viewer without a browser:
`otel-desktop-viewer query 'SHOW TABLES'`, `… query 'DESCRIBE spans'`, or any
read-only `SELECT` — how a span's arrival can be checked from a terminal.

A port already in use is the usual first problem: `4318` is the conventional
OTLP/HTTP port, shared with Jaeger and the OpenTelemetry Collector, and only one
process can bind it. Set `enabled = false` or stop the viewer to release it.

##### OpenLIT (Docker)

The compose step — save this compose file next to your `~/.codingdude` directory,
then bring it up:

```yaml
services:
  openlit:
    image: ghcr.io/openlit/openlit:latest
    container_name: openlit
    ports:
      - "3000:3000"   # UI
      - "4318:4318"   # OTLP/HTTP receiver — CodingDude's default endpoint
    environment:
      - INIT_DB_HOST=127.0.0.1
    volumes:
      - openlit-data:/app/data

volumes:
  openlit-data:
```

```bash
docker compose up -d
```

Then flip the switch — the endpoint already points at that receiver, so no value
needs changing:

```toml
[telemetry]
enabled = true
otlp_endpoint = "http://127.0.0.1:4318"
```

Read the traces at `http://127.0.0.1:3000`. A port already in use is the usual
first problem (`4318` is shared with Jaeger and the OpenTelemetry Collector);
change `otlp_endpoint` to match whatever you mapped instead.

**We deliberately do not use the OpenLIT Python SDK.** `openlit.init()`
instruments pydantic-ai through the same hooks `logfire.instrument_pydantic_ai()`
already uses, so running both produces duplicate spans; and only one global
`TracerProvider` can exist, so the second `set_tracer_provider` is a silent
no-op. OpenLIT is used strictly as an OTLP receiver: no new dependency, no
second instrumentation, and logfire stays the single source of spans.

Also not adopted, each for a reason: **Evals** (our evaluator grades against a
ticket contract, which a generic eval cannot), **Guardrails** (tool policy is
registry-locked in `functions.py`), **Vault** (a runtime availability
dependency), **Prompt Hub** (would move prompts out of the repo and break the
one-shot cacheable-prefix design), and **GPU monitoring** (we do not self-host
models).

**Cost views are subordinate to the ledger.** OpenLIT computes cost from its own
pricing database plus `gen_ai.usage.*` span attributes. `DelegatedSpend` →
`db.session_usage` remains the authoritative spend figure and is what the Budget
Cap reads. Treat any dashboard cost number as an independent estimate; where it
disagrees with the ledger, the ledger wins.

Not yet verified: that OpenLIT's dashboard renders spans produced by logfire's
pydantic-ai instrumentation. The spans are standard OTLP and the same spans are
confirmed to render in the OTel Desktop Viewer, so it should — but OpenLIT
itself has not been run against them here; start the container and confirm
before relying on it.

Configuration is read once per worker process, so a change takes effect on the
next run.

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
