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
"""R93-C: local-OTLP tracing for agent runs.

pydantic-ai emits OpenTelemetry spans for every model and tool call; Logfire
turns them into a trace. Until now none of that was switched on, so a failed
run arrived as a provider error string and the agent, request and tool involved
had to be inferred.

Traces are exported to a **local** OTLP collector (default
``http://127.0.0.1:4318``) and nowhere else: ``send_to_logfire=False`` means no
token, no account, no prompts leaving the machine. That is a deliberate
constraint, not a default to be relaxed later — run prompts contain repository
code.

Off unless ``[telemetry] enabled = true``: a collector that is not running must
never be the thing that breaks a run, so configuration failure degrades to
"tracing off" with one warning rather than raising.

R100: ``[telemetry] enabled`` is the *default*, not the last word. A run may
override it either way (the chat panel's trace checkbox), because recording is
expensive — one `chat` span carries the full prompt, the repository code in the
tool results and the system instructions (70-113KB observed live). Recording
every conversation forever fills the local store; recording none leaves no
forensics. Per-run consent is the only honest middle.

Configured once per process, by the engine's two agent-executing entry points
(`Engine.run` and `Engine.review`) — the first places where a run's own session
id exists, so a span can name the conversation it belongs to. The server
executes no runs, so instrumenting it would only add HTTP noise; every caller
that does execute (interactive worker, headless CLI, review mode) inherits the
call. The one exception is `evals.replay`, which opts out explicitly: it drives
a scripted model, so its token counts are simulated and must not enter a store
that is read as real spend (#361).

The evaluator (#296 `evaluate_work`) is *not* a third entry point to add: its
`WorkEvaluator` is constructed in `plugins.build_all`, and only an `Engine`
builds plugins, so an evaluator pass runs inside the caller's own process —
worker, CLI or review mode — after `Engine.run` has configured tracing. Its
agent spans therefore export under that run's session id already; #365 was
filed on the reading that the evaluator ran server-side, which no code path
does (server.py constructs no agent, builds no plugins and sets up no tracing).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

#: Set once `logfire.configure` has run. Guards against double configuration
#: (logfire warns and the second call would add a duplicate span processor).
#: One worker process executes exactly one run (ADR-0002) and review mode one
#: review per subprocess (#361), so a second call in a process can never mean a
#: second conversation — the first run's session attribution is the right one to
#: keep, and this guard is what preserves it.
_configured = False
#: Set once a configuration failure has been reported, so a worker that calls
#: this per run does not spam the same warning (`_configured` stays False on
#: failure, which is what lets a later, fixed call still succeed).
_warned = False


def traces_url(endpoint: str) -> str:
    """The OTLP/HTTP traces URL for a collector ``endpoint``.

    ``http://127.0.0.1:4318`` and ``http://127.0.0.1:4318/`` both become
    ``http://127.0.0.1:4318/v1/traces``; an endpoint that already names the
    traces path is left alone, so either spelling works.
    """
    base = endpoint.strip().rstrip('/')
    return base if base.endswith('/v1/traces') else f'{base}/v1/traces'


def configure_tracing(
    config: Config,
    *,
    enabled: bool | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
) -> bool:
    """Turn on agent tracing for this run. Returns True when enabled.

    ``enabled`` overrides ``[telemetry] enabled`` for this run (R100): ``None``
    means "the config decides", ``True``/``False`` force the decision. One
    worker process serves exactly one run, so that is all a per-conversation
    switch needs.

    ``session_id``/``run_id`` are attached to the span *resource* as
    ``codingdude.session_id``/``codingdude.run_id``. Without them a span is only
    attributable to pydantic-ai's own per-run ``gen_ai.conversation.id`` (a
    fresh UUID7; ``pydantic_ai/conversation.py``), which no CodingDude surface
    knows — so "monitor this conversation" would be impossible to answer.

    Never raises: a missing exporter, a malformed endpoint or an import failure
    is logged once and tracing stays off.
    """
    global _configured, _warned

    settings = getattr(config, 'telemetry', None)
    if settings is None:
        return False
    if not (settings.enabled if enabled is None else enabled):
        return False
    if _configured:
        return True
    try:
        import logfire
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        exporter = OTLPSpanExporter(endpoint=traces_url(settings.otlp_endpoint))
        resource_attributes = {}
        if session_id:
            resource_attributes['codingdude.session_id'] = session_id
        if run_id:
            resource_attributes['codingdude.run_id'] = run_id
        logfire.configure(
            send_to_logfire=False,
            service_name=settings.service_name,
            # Correlates every span in this process with one conversation.
            resource_attributes=resource_attributes,
            # Batched: an unreachable collector fails on the exporter's own
            # thread and cannot block or fail a model request.
            additional_span_processors=[BatchSpanProcessor(exporter)],
        )
        logfire.instrument_pydantic_ai()
    except Exception as exc:  # noqa: BLE001 - tracing must never fail a run
        if not _warned:
            _warned = True
            logger.warning('tracing disabled: %s', exc)
        return False
    _configured = True
    _warned = False
    logger.info(
        'TRACING_ENABLED endpoint=%s service=%s session=%s',
        traces_url(settings.otlp_endpoint), settings.service_name,
        session_id or '-',
    )
    return True
