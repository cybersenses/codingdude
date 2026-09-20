import { describe, expect, it } from 'vitest'

import { buildRepoQuestionPrompt } from './repoqa'

const structure = {
  files: [
    { path: 'main.py', lines: 12, symbols: [{ kind: 'function', name: 'run', line: 1 }] },
    { path: 'helpers.py', lines: 5, symbols: [{ kind: 'class', name: 'Util', line: 1 }] },
  ],
}
const archmap = {
  nodes: [
    { id: 'main.py', name: 'main.py', line: 12, orphan: true },
    { id: 'helpers.py', name: 'helpers.py', line: 5, orphan: false },
  ],
  edges: [['main.py', 'helpers.py']],
}

describe('buildRepoQuestionPrompt', () => {
  it('embeds the question, project outline and import edges', () => {
    const p = buildRepoQuestionPrompt('why is main.py orphaned?', structure, archmap)
    expect(p).toContain('why is main.py orphaned?')
    expect(p).toContain('main.py')
    expect(p).toContain('main.py -> helpers.py')
    expect(p).toContain('function run')
    expect(p).toContain('class Util')
  })

  it('demands file+line citations', () => {
    const p = buildRepoQuestionPrompt('q?', structure, archmap)
    expect(p.toLowerCase()).toContain('cite')
  })

  it('handles missing graphs without crashing', () => {
    const p = buildRepoQuestionPrompt('q?', null, null)
    expect(p).toContain('q?')
  })

  it('returns empty string for a blank question', () => {
    expect(buildRepoQuestionPrompt('  ', structure, archmap)).toBe('')
  })
})
