// CodingDude — a personal coding agent.
// Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as published
// by the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.
// R100: pure view logic for the OTel Traces panel and the prompt-row trace
// switch. Kept out of the JSX modules (the waterfall.ts / runs.ts pattern) so
// the wire-format rules can be tested without React in the room.

/** One span row, as `/sessions/{sid}/otel/spans` projects it. */
export interface OtelSpan {
  trace_id: string
  name: string
  start_time?: string | null
  duration_s?: number | null
  status?: string
  input_tokens?: number | null
  output_tokens?: number | null
  cost_usd?: number | null
  tool_name?: string | null
  model?: string | null
}

/** `/telemetry/status`: three independent legs, each failing differently. */
export interface OtelStatus {
  config_enabled: boolean
  otlp_endpoint: string
  collector_reachable: boolean
  viewer_endpoint: string
  viewer_reachable: boolean
  viewer_error?: string | null
}

export interface TraceSwitch {
  on: boolean
  dot: string
  detail: string
  label: string
}

export type SpanKind = 'model' | 'tool' | 'agent' | 'other'

/** The span name carries the kind: pydantic-ai names spans `chat <model>`,
 * `execute_tool <tool>` and `invoke_agent <agent>`. */
export function spanKind(name: string): SpanKind {
  if (name.startsWith('chat')) return 'model'
  if (name.startsWith('execute_tool')) return 'tool'
  if (name.startsWith('invoke_agent')) return 'agent'
  return 'other'
}

export const SPAN_KIND_COLOR: Record<SpanKind, string> = {
  model: 'text-brand-400',
  tool: 'text-accent',
  agent: 'text-warning',
  other: 'text-ink-muted',
}

export interface TraceGroup {
  id: string
  spans: OtelSpan[]
  inputTokens: number
  cost: number
}

/** Group spans by `trace_id` — the collector's own join key, so one
 * conversation reads as a turn per trace instead of a flat list. */
export function groupSpansByTrace(spans: OtelSpan[] | null | undefined): TraceGroup[] {
  const byTrace = new Map<string, OtelSpan[]>()
  for (const span of spans || []) {
    const group = byTrace.get(span.trace_id)
    if (group) group.push(span)
    else byTrace.set(span.trace_id, [span])
  }
  return [...byTrace.entries()].map(([id, group]) => ({
    id,
    // The API returns newest-first; inside one trace, read it top-down.
    spans: [...group].reverse(),
    inputTokens: group.reduce((n, s) => n + (s.input_tokens || 0), 0),
    cost: group.reduce((n, s) => n + (s.cost_usd || 0), 0),
  }))
}

/** Resolve the tri-state switch (`null` = never touched here) into what the
 * row renders. The dot is the honest part: with nothing listening on the OTLP
 * port a BatchSpanProcessor drops spans on its own thread and the run looks
 * completely normal, so "recording is on" must never be the only signal. */
export function traceSwitchState(
  otel: boolean | null,
  telemetry: OtelStatus | null | undefined,
): TraceSwitch {
  // Neither a choice here nor an answer from /telemetry/status: the server's
  // [telemetry] setting decides and we do not know what it says. Rendering
  // "off" in that state is a claim the code cannot support - the run may be
  // recording, because an absent override is exactly what lets the config win.
  const unknown = otel === null && !telemetry
  const on = otel === null ? Boolean(telemetry && telemetry.config_enabled) : otel
  const dot = !on
    ? 'bg-neutral-600'
    : telemetry && telemetry.collector_reachable ? 'bg-success' : 'bg-warning'
  const detail = unknown
    ? 'recording setting unknown - /telemetry/status has not answered, so the config decides'
    : !on
      ? 'recording is off for this run'
      : !telemetry
        ? 'collector state unknown'
        : telemetry.collector_reachable
          ? `recording spans to ${telemetry.otlp_endpoint}`
          : `nothing is listening on ${telemetry.otlp_endpoint} - spans will be dropped`
  const state = unknown ? 'unknown' : on ? 'on' : 'off'
  return { on, dot, detail, label: `${state}: ${detail}` }
}
