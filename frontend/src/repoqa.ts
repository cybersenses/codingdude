// #102 (R43): repo Q&A — a human question grounded in the project's
// structure outline and architecture map, answered with file+line citations
// through the normal agent run flow.

export function buildRepoQuestionPrompt(
  question: string,
  structure: { files: Array<{ path: string; lines: number; symbols: Array<{ kind: string; name: string }> }> } | null,
  archmap: { edges: string[][] } | null,
): string {
  const q = question.trim()
  if (!q) return ''

  const outline = (structure?.files || [])
    .map((f) => {
      const syms = f.symbols
        .map((s) => `${s.kind} ${s.name}`)
        .slice(0, 15)
        .join(', ')
      return `- ${f.path} (${f.lines} lines)${syms ? `: ${syms}` : ''}`
    })
    .join('\n')

  const edges = (archmap?.edges || [])
    .map(([a, b]) => `- ${a} -> ${b}`)
    .join('\n')

  return [
    'Answer this question about my project:',
    '',
    q,
    '',
    'Answer for a human reading the code for the first time. CITE the file (and line number when you know it) for every claim — e.g. (src/app.py:42). If the answer is not determinable from the project, say so plainly.',
    '',
    'Project outline:',
    outline || '(no source files indexed)',
    '',
    'Import graph:',
    edges || '(no cross-file imports found)',
    '',
    'Read the relevant files for context before answering; do not change anything.',
  ].join('\n')
}
