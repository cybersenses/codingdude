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
// #231/#233: per-tab poll failures for the bottom dock. Each tab used to carry
// its own error key (configError, memoryError) and only some were rendered, so
// a failing fetch looked like a tab that was still loading for ever. Errors now
// live in one map keyed by tab and stamped with the session they belong to, so
// a stale error cannot follow the user to another tab or another session.
//
// Kept out of App.jsx and free of React so the decision is testable: no vitest
// file imports App.jsx, which is how the #233 version shipped with no tests.

export interface PollError {
  /** Session the failure belongs to; null when there is no session at all. */
  sessionId: string | null
  message: string
}

/** Tab name -> the last failure for that tab. */
export type PollErrors = Record<string, PollError>

/** Record a failed poll for `tab`, leaving every other tab's error intact. */
export function pollFailure(
  errors: PollErrors | undefined,
  tab: string,
  sessionId: string | null | undefined,
  err: unknown,
): PollErrors {
  return {
    ...errors,
    [tab]: {
      sessionId: sessionId ?? null,
      message: String(err instanceof Error ? err.message : err),
    },
  }
}

/**
 * Drop `tab`'s error after a successful poll, leaving the others alone.
 *
 * Returns the incoming value untouched when there was nothing to clear, so a
 * healthy tab does not hand `data` a new object every 4 seconds just to say
 * "still fine". (The dock itself re-renders regardless — callers spread `data`
 * — but a stable `pollErrors` keeps the map referentially equal.)
 */
export function pollCleared(errors: PollErrors | undefined, tab: string): PollErrors | undefined {
  if (!errors?.[tab]) return errors
  const next = { ...errors }
  delete next[tab]
  return next
}

/**
 * The message to show for `tab`, or null when it has no failure for the
 * session currently on screen.
 *
 * The session check is the whole point: without it an error from session A
 * would be rendered under session B, which is worse than showing nothing.
 */
export function tabError(
  errors: PollErrors | undefined,
  tab: string,
  sessionId: string | null | undefined,
): string | null {
  const e = errors?.[tab]
  if (!e || e.sessionId !== (sessionId ?? null)) return null
  return e.message
}
