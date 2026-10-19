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
// #77: run-output view. Trace events carry run_id (R31); group them so the
// Output tab can show one run's activity stream and let the user pick a run.

export interface TraceEvent {
  run_id?: string
  type: string
  ts?: string
  [key: string]: unknown
}

/** Group trace events by run_id, preserving first-appearance order (the API
 * returns newest-first, so that order carries through); events without a
 * run_id (pre-R31 traces) land under '(unattributed)'. In-run order kept. */
export function groupEventsByRun(events: TraceEvent[]): Record<string, TraceEvent[]> {
  const groups: Record<string, TraceEvent[]> = {}
  for (const e of events) {
    const key = e.run_id || '(unattributed)'
    ;(groups[key] ??= []).push(e)
  }
  return groups
}

/** The run to display: the user's selection if it still exists, else the
 * newest run, else null. */
export function pickRunId(
  groups: Record<string, TraceEvent[]>,
  selected: string | null,
): string | null {
  if (selected && groups[selected]) return selected
  const keys = Object.keys(groups)
  return keys.length ? keys[0] : null
}
