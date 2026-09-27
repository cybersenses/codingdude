// #154 (R46): CFG seam tests — red first.
import { describe, expect, it } from 'vitest'

import { cfgMermaid } from './cfgView'

const cfg = {
  function: 'f',
  blocks: [
    { id: 0, lines: ['return 1'], reachable: true },
    { id: 1, lines: ['dead = 2'], reachable: false },
  ],
  edges: [{ src: 0, dst: 1, kind: 'flow' }],
}

describe('cfgMermaid', () => {
  it('renders one node per block with source text', () => {
    const m = cfgMermaid(cfg)
    expect(m).toContain('flowchart TD')
    expect(m).toContain('"return 1"')
    expect(m).toContain('"dead = 2"')
  })

  it('colors reachable green and dead red', () => {
    const m = cfgMermaid(cfg)
    expect(m).toContain('fill:#22c55e')
    expect(m).toContain('fill:#ef4444')
  })

  it('renders edges with kind labels', () => {
    expect(cfgMermaid(cfg)).toContain('-->|flow|')
  })

  it('empty cfg yields empty diagram', () => {
    expect(cfgMermaid(null)).toBe('')
  })

  it('escapes quotes in source lines', () => {
    const m = cfgMermaid({
      function: 'f',
      blocks: [{ id: 0, lines: ['x = "hi"'], reachable: true }],
      edges: [],
    })
    expect(m).not.toMatch(/\["[^"]*"[^"]*"\]/)
    expect(m).toContain('#quot;')
  })
})
