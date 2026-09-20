import { describe, expect, it } from 'vitest'
import { buildDesignDocPrompt } from './designdoc'

const tour = [
  { label: 'run started', ts: 1 },
  { label: 'edit_file → edited src/codingdude/widget.py', ts: 2 },
  { label: 'pytest (gates)', ts: 3 },
  { label: 'run finished', ts: 4 },
]

describe('buildDesignDocPrompt', () => {
  it('builds an ADR-writing prompt from the run narrative', () => {
    const p = buildDesignDocPrompt('fix flaky gate', tour)
    expect(p).toContain('fix flaky gate')
    expect(p).toContain('src/codingdude/widget.py')
    expect(p).toContain('pytest (gates)')
    expect(p).toMatch(/ADR|design document/i)
  })

  it('demands a full ADR structure', () => {
    const p = buildDesignDocPrompt('q', tour)
    for (const section of ['Context', 'Decision', 'Consequences']) {
      expect(p).toContain(section)
    }
  })

  it('returns null without a tour', () => {
    expect(buildDesignDocPrompt('q', [])).toBeNull()
  })
})
