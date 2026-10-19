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
// R29 (#58): decide whether the UI should reattach to a live run's SSE stream
// on boot/refresh — the selected session has a live run and we are not
// already attached to one.

export function runToReattach(
  liveRuns: Map<string, string>,
  activeSession: string | null,
  attachedRun: string | null,
): string | null {
  if (!activeSession || attachedRun) return null
  return liveRuns.get(activeSession) ?? null
}

// #78: a run that bounces its own server must outlive the outage — the worker
// (post-#73) keeps running and persists its outcome, so the UI retries with a
// budget sized for a real restart (~2 minutes) before giving up.
export const SSE_MAX_RETRIES = 30

export function sseRetryDelayMs(attempt: number): number {
  return Math.min(1000 * (attempt + 1), 5000)
}
