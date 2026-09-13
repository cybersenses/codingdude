# R10 Tracer — Cost & latency telemetry (`telemetry`)

Thin vertical slice: per-run token/cost/duration accounting with config-driven
pricing and a tokens-only fallback (ratified decision #8: pricing mirrors the
`context_limit` config pattern; never duplicate R3's context snapshot).

## Design

### Config (`ModelLineup.pricing`)
`pricing: dict[str, dict[str, float]] | None = None` — map of model-name →
`{'input': USD/1M in-tokens, 'output': USD/1M out-tokens}`. Key may be the
exact model name or a distinguishing substring (first longest match wins).

### New `src/codingdude/telemetry.py`
- `estimate_cost(pricing, model_name, input_tokens, output_tokens) -> float | None`
  — exact key, then longest substring key; `None` when unpriced (tokens-only
  fallback, never a fabricated number).
- `run_usage_event(model_name, requests, input_tokens, output_tokens,
  cost_usd, duration_s, pricing)` → the `RUN_USAGE` trace event dict; cost is
  the provider-reported `usage.cost` when present, else
  `estimate_cost(...)`, else `None` (with `cost_source`:
  `'provider'|'pricing'|'unpriced'`).

### Engine wiring
`Engine.run` times the run and, where it already records main-model usage,
emits `RUN_USAGE` via `traced(...)` so the numbers land in both the trace
JSONL and the SSE stream. Aux-model calls stay in the `usage` table as today
(no change).

Non-goals (later thickening): per-tool-call latency breakdown, UI panel,
agent self-query of remaining budget, per-step cost attribution.

## Tests (`tests/test_telemetry.py`)
Seams: pure `telemetry` functions + `Engine.run` with a scripted/TestModel run
inspecting the emitted events.
1. estimate_cost exact key; substring key; unpriced → None
2. run_usage_event prefers provider cost, falls back to pricing, marks unpriced
3. Engine.run emits RUN_USAGE with duration_s >= 0 and token totals from the model usage
4. config loads `pricing` from TOML
