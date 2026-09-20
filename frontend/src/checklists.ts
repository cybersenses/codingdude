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
