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
