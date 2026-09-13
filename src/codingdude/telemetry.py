"""R10: per-run cost/latency telemetry.

Cost comes from the provider when it reports it; otherwise from config-driven
pricing (`models.pricing`); otherwise the event is explicitly 'unpriced' —
never a fabricated number.
"""

from typing import Any

# pricing: model-name -> {'input': USD/1M, 'output': USD/1M}; keys may be
# exact model names or distinguishing substrings.
Pricing = dict[str, dict[str, float]]


def estimate_cost(
    pricing: Pricing | None,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """USD cost for a usage volume, or None when the model is unpriced."""
    if not pricing:
        return None
    rates = pricing.get(model_name)
    if rates is None:
        matches = [k for k in pricing if k in model_name]
        if not matches:
            return None
        rates = pricing[max(matches, key=len)]
    return (
        input_tokens * rates.get('input', 0.0) * 1e-6
        + output_tokens * rates.get('output', 0.0) * 1e-6
    )


def run_usage_event(
    *,
    model_name: str,
    requests: int,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    duration_s: float,
    pricing: Pricing | None = None,
) -> dict[str, Any]:
    """The RUN_USAGE trace event: tokens + cost + duration for one run."""
    if cost_usd is not None:
        source = 'provider'
    else:
        cost_usd = estimate_cost(pricing, model_name, input_tokens, output_tokens)
        source = 'pricing' if cost_usd is not None else 'unpriced'
    return {
        'type': 'RUN_USAGE',
        'model': model_name,
        'requests': requests,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'cost_usd': cost_usd,
        'cost_source': source,
        'duration_s': round(duration_s, 3),
    }
