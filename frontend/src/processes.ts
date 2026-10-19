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
// R31 #63: process visibility. One row per shell process the session
// spawned (from GET /sessions/{id}/processes), tracked until it exits.

export interface ProcessEntry {
  pid: number
  command: string
  started_at: string
  status: string
  exit_code: number | null
  background: boolean
}

/** Merge a fresh server snapshot into displayed state: newest rows win,
 * but a row never disappears from the panel once seen (tracked until closed). */
export function mergeProcesses(existing: ProcessEntry[], fetched: ProcessEntry[]): ProcessEntry[] {
  const byKey = new Map<string, ProcessEntry>()
  const key = (p: ProcessEntry) => `${p.pid}:${p.started_at}`
  for (const p of fetched) byKey.set(key(p), p)
  for (const p of existing) {
    const k = key(p)
    // Keep the seen row if the server no longer lists it; prefer newer data otherwise.
    if (!byKey.has(k)) byKey.set(k, p)
  }
  return [...byKey.values()].sort((a, b) =>
    (b.started_at || '').localeCompare(a.started_at || ''),
  )
}

/** Rows currently running — the Processes panel lists only active ones. */
export function activeProcesses(processes: ProcessEntry[]): ProcessEntry[] {
  return processes.filter((p) => p.status === 'running')
}

/** One-line summary for the panel: pid + short command + live/exited badge. */
export function describeProcess(p: ProcessEntry): string {
  const cmd = p.command.length > 80 ? p.command.slice(0, 77) + '…' : p.command
  const state = p.status === 'running' ? 'running' : `exited (${p.exit_code ?? '?'})`
  return `[${p.pid}] ${state} — ${cmd}`
}
