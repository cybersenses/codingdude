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
/** Guided tour of a run (ticket #104): run trace events → ordered human steps. */

const tsOf = (v: unknown): number => (typeof v === 'number' ? v : Date.parse(String(v)) || 0)

export interface TourStep {
  label: string
  ts: number
}

/** Events worth narrating; everything else (text streaming etc.) is noise. */
const WORTHY = new Set([
  'RUN_STARTED',
  'RUN_FINISHED',
  'RUN_ERROR',
  'TOOL_CALL_START',
  'TOOL_CALL_END',
  'EDIT_APPLIED',
])

export function buildTour(events: Array<Record<string, unknown>>): TourStep[] {
  const sorted = [...events].sort((a, b) => tsOf(a.ts) - tsOf(b.ts))
  const steps: TourStep[] = []
  const openCalls = new Map<string, number>() // tool_name → start ts
  const pendingEdit = new Map<string, string>() // tool_name → edited path

  for (const e of sorted) {
    const type = String(e.type)
    if (!WORTHY.has(type)) continue
    const ts = tsOf(e.ts)
    if (type === 'TOOL_CALL_START') {
      const name = String(e.tool_name ?? 'tool')
      openCalls.set(name, ts)
    } else if (type === 'TOOL_CALL_END') {
      const name = String(e.tool_name ?? 'tool')
      const start = openCalls.get(name)
      openCalls.delete(name)
      const edit = pendingEdit.get(name)
      pendingEdit.delete(name)
      steps.push({ label: `${name}${edit ? ` → edited ${edit}` : ''}`, ts: start ?? ts })
    } else if (type === 'EDIT_APPLIED') {
      // EDIT_APPLIED can land before or after TOOL_CALL_END; keep the path
      // with whichever step is still open, else emit its own step.
      let attached = false
      for (const [name] of openCalls) {
        if (name === 'edit_file') { pendingEdit.set(name, String(e.path)); attached = true }
      }
      if (!attached) steps.push({ label: `edited ${String(e.path)}`, ts })
    } else {
      steps.push({ label: type === 'RUN_STARTED' ? 'run started' : type === 'RUN_ERROR' ? 'run failed' : 'run finished', ts })
    }
  }

  for (const [name, ts] of openCalls) {
    const edit = pendingEdit.get(name)
    steps.push({ label: `${name}${edit ? ` → edited ${edit}` : ''}${name === 'edit_file' ? '' : ' (running…)'}`, ts })
  }
  return steps.sort((a, b) => a.ts - b.ts)
}
