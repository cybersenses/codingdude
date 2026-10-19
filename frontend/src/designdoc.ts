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
/** Design-doc/ADR from a run (ticket #105): turn the run tour into an
 * ADR-drafting prompt executed through the normal agent run flow. */

export interface TourStep {
  label: string
  ts: number
}

export function buildDesignDocPrompt(goal: string, tour: TourStep[]): string | null {
  if (!tour.length) return null
  const narrative = tour.map((s) => `- ${s.label}`).join('\n')
  return [
    `Draft a design document (ADR-style) for the work done in this run.`,
    ``,
    `Goal of the run: ${goal}`,
    ``,
    `What actually happened (chronological):`,
    narrative,
    ``,
    'Read the touched files listed above for context before writing.',
    'Respond with the design document only, using exactly these sections:',
    `# Title`,
    `## Status (proposed)`,
    `## Context — the problem and forces at play`,
    `## Decision — what was chosen and why, naming concrete files/symbols`,
    `## Consequences — benefits, trade-offs, follow-ups`,
    `Do not modify any files.`,
  ].join('\n')
}
