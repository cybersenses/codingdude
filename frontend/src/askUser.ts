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

/** #145: pending prompts must not outlive the run. On stop or terminal
 * event, strip ask/gate cards from every message (the worker behind them is
 * gone — answering would just 404). Pure: returns a new array. */
export function clearPendingPrompts<T extends { ask?: unknown; gate?: unknown }>(
  messages: T[],
): T[] {
  return messages.map((m) => ({ ...m, ask: null, gate: null }))
}

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
