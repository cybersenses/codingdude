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
// #93 (R41): distilled checklists as user-invokable agent actions.
// Pure seam: parse checklist metadata + build the run prompt.

export function checklistTitle(md: string): string {
  const h1 = md.split('\n').find((l) => l.startsWith('# '))
  const raw = (h1 ?? '').replace(/^#\s+/, '').trim()
  return raw.replace(/\s+Checklist$/, '').trim() || raw
}

export function checklistPrompt(
  name: string,
  checklistMd: string,
  target: string,
): string {
  return [
    `Work through the "${checklistTitle(checklistMd)}" checklist (${name}) ${target ? `for: ${target}` : 'against the project as a whole'}.`,
    '',
    'For every checklist item, mark it NEEDS WORK, PARTIAL, PASS and cite the concrete evidence you inspected (file, test output, screenshot) — never a report alone. Fix nothing yet: end with a prioritized list of the NEEDS WORK items so I can decide what to fix.',
    '',
    'The checklist:',
    '```markdown',
    checklistMd.trim(),
    '```',
  ].join('\n')
}
