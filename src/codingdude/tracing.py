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

Configured once per process, in the worker (workers are what execute runs; the
server executes none, so instrumenting it would only add HTTP noise).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

#: Set once `logfire.configure` has run. Guards against double configuration
#: (logfire warns and the second call would add a duplicate span processor).
_configured = False


def traces_url(endpoint: str) -> str:
    """The OTLP/HTTP traces URL for a collector ``endpoint``.

    ``http://127.0.0.1:4318`` and ``http://127.0.0.1:4318/`` both become
    ``http://127.0.0.1:4318/v1/traces``; an endpoint that already names the
    traces path is left alone, so either spelling works.
    """
    base = endpoint.strip().rstrip('/')
    return base if base.endswith('/v1/traces') else f'{base}/v1/traces'


def configure_tracing(config: Config) -> bool:
    """Turn on agent tracing from ``[telemetry]``. Returns True when enabled.

    Never raises: a missing exporter, a malformed endpoint or an import failure
    is logged once and tracing stays off.
    """
    global _configured

    settings = getattr(config, 'telemetry', None)
    if settings is None or not settings.enabled:
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
        logfire.configure(
            send_to_logfire=False,
            service_name=settings.service_name,
            # Batched: an unreachable collector fails on the exporter's own
            # thread and cannot block or fail a model request.
            additional_span_processors=[BatchSpanProcessor(exporter)],
        )
        logfire.instrument_pydantic_ai()
    except Exception as exc:  # noqa: BLE001 - tracing must never fail a run
        logger.warning('tracing disabled: %s', exc)
        return False
    _configured = True
    logger.info(
        'TRACING_ENABLED endpoint=%s service=%s',
        traces_url(settings.otlp_endpoint), settings.service_name,
    )
    return True
