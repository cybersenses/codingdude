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
