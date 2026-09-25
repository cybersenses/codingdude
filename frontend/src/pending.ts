// #147: durable pending interactions. ASK_USER / GATE_REQUEST events are
// persisted to the session trace (with an ASK_USER_RESOLVED / GATE_RESOLVED
// marker when answered or timed out). After a refresh, the UI can restore
// the pending card if the run is still alive.

export interface TraceEvent {
  run_id?: string
  type: string
  ts?: string
  [key: string]: unknown
}

export type PendingInteraction =
  | { kind: 'ask'; questions: unknown[] }
  | { kind: 'gate'; command: string }

const REQUEST = new Set(['ASK_USER', 'GATE_REQUEST'])
const RESOLVED = new Set(['ASK_USER_RESOLVED', 'GATE_RESOLVED'])

/** The still-open interaction for `runId`, or null. Chronologically last
 * request-or-resolution wins: a resolution after the request means nothing
 * is pending. Events arrive newest-first from the trace API; ordering is
 * derived from `ts` (stable sort, missing ts keeps file order). */
export function pickPending(
  events: TraceEvent[],
  runId: string | null,
): PendingInteraction | null {
  if (!runId) return null
  const relevant = events
    .map((e, i) => ({ e, i }))
    .filter(({ e }) => e.run_id === runId && (REQUEST.has(e.type) || RESOLVED.has(e.type)))
  if (!relevant.length) return null
  relevant.sort((a, b) => {
    const ta = a.e.ts || ''
    const tb = b.e.ts || ''
    if (ta !== tb) return ta < tb ? -1 : 1
    return a.i - b.i
  })
  const last = relevant[relevant.length - 1].e
  if (last.type === 'ASK_USER') return { kind: 'ask', questions: last.questions || [] }
  if (last.type === 'GATE_REQUEST') return { kind: 'gate', command: String(last.command || '') }
  return null
}
