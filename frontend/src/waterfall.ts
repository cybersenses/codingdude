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
// #84 (R38 phase 1): turn a run's trace events into spans for the waterfall
// timeline. Pure module — no React, no deps — so it stays unit-testable
// (runs.ts pattern).

import type { TraceEvent } from './runs'

export interface WfSpan {
  kind: 'tool' | 'edit' | 'gate' | 'marker'
  label: string
  /** seconds relative to the first timestamped event */
  start: number
  end: number
  /** span had a START but no END — closed at the last event time */
  unclosed?: boolean
}

interface WfResult {
  spans: WfSpan[]
  /** total duration in seconds (last timestamped event minus first) */
  total: number
}

const MARKER_KINDS: Record<string, WfSpan['kind']> = {
  EDIT_APPLIED: 'edit',
  GATE_REQUEST: 'gate',
}

function labelFor(type: string, e: TraceEvent): string {
  if (type === 'TOOL_CALL_START' || type === 'TOOL_CALL_END') return String(e.tool_name ?? 'tool')
  if (type === 'EDIT_APPLIED') return String(e.path ?? 'edit')
  if (type === 'DELEGATION_STARTED') return String(e.task ?? 'delegation').slice(0, 40)
  return type
}

function seconds(iso: string): number {
  return new Date(iso).getTime() / 1000
}

/** Pair START/END tool events (LIFO, so nested delegations work) and emit
 * instant events as zero-length markers. Times become seconds relative to
 * the first timestamped event. Unclosed spans are closed at the end. */
export function buildSpans(events: TraceEvent[]): WfResult {
  const timed = events.filter((e) => e.ts)
  if (!timed.length) return { spans: [], total: 0 }
  const t0 = seconds(timed[0].ts as string)
  const tEnd = seconds(timed[timed.length - 1].ts as string)

  const spans: WfSpan[] = []
  const open: { label: string; start: number; ts: string }[] = []

  for (const e of timed) {
    const type = e.type
    const t = seconds(e.ts as string) - t0
    if (type === 'TOOL_CALL_START') {
      open.push({ label: labelFor(type, e), start: t, ts: e.ts as string })
    } else if (type === 'TOOL_CALL_END') {
      // Close the most recent open span with the same tool name (LIFO);
      // fall back to the latest open span if names drifted.
      let idx = -1
      for (let i = open.length - 1; i >= 0; i--) {
        if (open[i].label === labelFor(type, e)) { idx = i; break }
      }
      const s = open.splice(idx >= 0 ? idx : open.length - 1, 1)[0]
      if (s) spans.push({ kind: 'tool', label: s.label, start: s.start, end: t })
    } else if (type === 'DELEGATION_STARTED') {
      open.push({ label: labelFor(type, e), start: t, ts: e.ts as string })
    } else if (type === 'DELEGATION_COMPLETED') {
      const s = open.splice(open.length - 1, 1)[0]
      if (s) spans.push({ kind: 'tool', label: s.label, start: s.start, end: t })
    } else if (MARKER_KINDS[type]) {
      spans.push({ kind: MARKER_KINDS[type], label: labelFor(type, e), start: t, end: t })
    }
  }
  for (const s of open) spans.push({ kind: 'tool', label: s.label, start: s.start, end: tEnd - t0, unclosed: true })

  spans.sort((a, b) => a.start - b.start)
  return { spans, total: tEnd - t0 }
}
