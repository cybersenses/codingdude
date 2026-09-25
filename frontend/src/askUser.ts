// Pure seam for AskUserCard: turn per-question UI state (picked option(s),
// typed "Other…" text, free-text answers) into the answers payload the
// /runs/{id}/ask endpoint expects. No DOM, no fetch — fully unit-testable.
export interface AskQuestion {
  question: string
  options?: string[]
  multi?: boolean
}

export type Picks = Record<string, string | string[]>
export type Texts = Record<string, string>

export function buildAnswers(
  questions: AskQuestion[],
  picks: Picks,
  texts: Texts,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const q of questions) {
    const other = (texts[q.question] ?? '').trim()
    if (other) {
      out[q.question] = other
      continue
    }
    const pick = picks[q.question]
    if (q.multi) out[q.question] = Array.isArray(pick) ? pick : []
    else out[q.question] = typeof pick === 'string' ? pick : ''
  }
  return out
}
