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
"""R100: read agent spans out of the local OpenTelemetry store.

The store is the OTel Desktop Viewer's DuckDB file. This module **never opens
that file**, and that is a hard constraint, not a preference:

- DuckDB is single-writer. The viewer holds the database read-write for its
  whole lifetime, so a second process cannot take the lock — not even
  read-only — and an attempt fails or, worse, races a writer.
- The viewer publishes the supported door: a read-only ``query`` JSON-RPC
  method served by the process that already owns the file (``GET
  /openrpc.json`` describes it, ``POST /rpc`` serves it). Its own agent guide
  says to reuse the running viewer and never stop one you did not start.

So every read here is a JSON-RPC call to the running viewer. If someone later
"optimises" this into a direct ``duckdb.connect``, the panel breaks whenever a
viewer is running — which is always.

Two things worth stating in code rather than in a commit message:

- ``query`` takes **raw SQL**; there is no parameter binding. Session ids are
  therefore validated against :data:`_SESSION_ID` and anything else is
  rejected — never escaped, never interpolated unvalidated.
- ``start_time``/``end_time`` are UBIGINT **nanoseconds**. A real value
  (1.79e18) exceeds JavaScript's ``2^53``, so the conversion happens here and
  the API hands the UI ISO strings and float seconds. Sending raw nanoseconds
  would silently corrupt every timestamp in the browser.
"""
from __future__ import annotations

import logging
import re
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

#: The viewer's HTTP port. Its OTLP receivers (4317 gRPC / 4318 HTTP) speak
#: OTLP, not SQL — the query API lives beside the web UI, not beside ingest.
DEFAULT_VIEWER_ENDPOINT = 'http://127.0.0.1:8000'

#: Session ids are minted by the server (``secrets.token_urlsafe``) and appear
#: in URLs, so 64 characters of that alphabet is a generous ceiling.
_SESSION_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

#: OTel ``SpanStatusCode``: 0 unset, 1 ok, 2 error.
_STATUS_CODES = {0: 'unset', 1: 'ok', 2: 'error'}

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_REQUEST_TIMEOUT_S = 10.0
_MAX_LIMIT = 500

#: The projection is deliberately narrow. ``gen_ai.input.messages``,
#: ``gen_ai.output.messages`` and ``gen_ai.system_instructions`` hold the full
#: prompt and repository code (70-113KB each, observed live) — shipping those
#: to a browser panel would make it unusable and would spray code around the UI
#: for no benefit. Tokens, cost and timing answer "what happened here".
_SPAN_SQL = """
SELECT
    CAST(trace_id AS VARCHAR) AS trace_id,
    name,
    start_time,
    (end_time - start_time) AS duration_ns,
    status_code,
    CAST(attributes['gen_ai.usage.input_tokens'] AS BIGINT) AS input_tokens,
    CAST(attributes['gen_ai.usage.output_tokens'] AS BIGINT) AS output_tokens,
    CAST(attributes['operation.cost'] AS DOUBLE) AS cost_usd,
    CAST(attributes['gen_ai.tool.name'] AS VARCHAR) AS tool_name,
    CAST(attributes['gen_ai.request.model'] AS VARCHAR) AS model
FROM spans
WHERE resource.attributes['codingdude.session_id'] = '{session_id}'
ORDER BY start_time DESC
LIMIT {limit}
"""
# The session id is interpolated, not bound: see the module docstring. It has
# already passed `valid_session_id`, which is the only reason this is safe.


class ViewerUnavailable(RuntimeError):
    """The viewer could not answer — not running, wrong port, or bad query."""


def valid_session_id(session_id: str) -> str:
    """Return the session id, or raise ``ValueError``.

    Fail fast and loudly, at the boundary. Rejecting is safer than escaping:
    an escaped value could still be a valid id for the wrong conversation.
    """
    if not _SESSION_ID.match(session_id or ''):
        raise ValueError(f'invalid session id: {session_id!r}')
    return session_id


def _clamp(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return 100
    return max(1, min(value, _MAX_LIMIT))


def _rpc(
    method: str, params: dict, *, endpoint: str = DEFAULT_VIEWER_ENDPOINT
) -> object:
    """POST one JSON-RPC request to the viewer; raise on any failure."""
    url = f'{endpoint.rstrip("/")}/rpc'
    body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    try:
        response = httpx.post(url, json=body, timeout=_REQUEST_TIMEOUT_S)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - every failure is the same answer
        raise ViewerUnavailable(f'{url}: {exc}') from exc
    if not isinstance(payload, dict):
        raise ViewerUnavailable(f'{url}: unexpected response {payload!r:.120}')
    if payload.get('error'):
        error = payload['error']
        detail = error.get('message') if isinstance(error, dict) else error
        raise ViewerUnavailable(str(detail or error))
    return payload.get('result')


def query(
    sql: str, *, limit: int = 100, endpoint: str = DEFAULT_VIEWER_ENDPOINT
) -> dict:
    """Run one read-only SQL query through the running viewer."""
    result = _rpc('query', {'sql': sql, 'limit': _clamp(limit)}, endpoint=endpoint)
    if not isinstance(result, dict):
        raise ViewerUnavailable(f'unexpected query result: {result!r:.120}')
    return {
        'columns': result.get('columns') or [],
        'rows': result.get('rows') or [],
        'truncated': bool(result.get('truncated')),
    }


def _ns_to_iso(nanoseconds: object) -> str | None:
    """UBIGINT nanoseconds -> ISO-8601 UTC. Exact, and never a float.

    The viewer answers with a JSON number (Python ``int``) or null; anything
    else is a shape we do not claim to understand, so it renders as no time
    rather than a wrong one.
    """
    if not isinstance(nanoseconds, int):
        return None
    return (_EPOCH + timedelta(microseconds=nanoseconds // 1000)).isoformat()


def _rows_as_dicts(result: dict) -> list[dict[str, object]]:
    names = [column.get('name') for column in result['columns']]
    return [dict(zip(names, row, strict=False)) for row in result['rows']]


def _span(row: dict[str, object]) -> dict:
    duration_ns = row.get('duration_ns')
    name = row.get('name')
    status_code = row.get('status_code')
    return {
        'trace_id': row.get('trace_id'),
        'name': name if isinstance(name, str) else '',
        'start_time': _ns_to_iso(row.get('start_time')),
        'duration_s': (
            round(duration_ns / 1_000_000_000, 3)
            if isinstance(duration_ns, int) else None
        ),
        'status': (
            _STATUS_CODES.get(status_code, 'unset')
            if isinstance(status_code, int) else 'unset'
        ),
        'input_tokens': row.get('input_tokens'),
        'output_tokens': row.get('output_tokens'),
        'cost_usd': row.get('cost_usd'),
        'tool_name': row.get('tool_name'),
        'model': row.get('model'),
    }


def session_spans(
    session_id: str, *, limit: int = 200, endpoint: str = DEFAULT_VIEWER_ENDPOINT
) -> dict:
    """Spans recorded for one conversation, newest first."""
    valid_session_id(session_id)
    result = query(
        _SPAN_SQL.format(session_id=session_id, limit=_clamp(limit)),
        limit=_clamp(limit),
        endpoint=endpoint,
    )
    spans = [_span(row) for row in _rows_as_dicts(result)]
    return {'spans': spans, 'truncated': result['truncated']}


def viewer_reachable(
    endpoint: str = DEFAULT_VIEWER_ENDPOINT,
) -> tuple[bool, str | None]:
    """Is the query API answering? Never raises: the answer IS the result."""
    try:
        query('SELECT 1 AS ok', limit=1, endpoint=endpoint)
    except ViewerUnavailable as exc:
        return False, str(exc)
    return True, None


def collector_reachable(otlp_endpoint: str, *, timeout: float = 0.5) -> bool:
    """TCP-probe the OTLP/HTTP receiver.

    A ``BatchSpanProcessor`` drops spans on its own thread when nothing is
    listening, so a run with tracing on and no collector looks exactly like a
    successful run. The settings row needs this answer to say otherwise.
    """
    parsed = urlparse(otlp_endpoint or '')
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
