import { describe, expect, it } from 'vitest'

import { callgraphMermaid } from './callgraph'

describe('callgraphMermaid', () => {
  it('renders nodes and edges', () => {
    const g = {
      nodes: [
        { id: 'main', name: 'main', line: 1, orphan: false },
        { id: 'helper', name: 'helper', line: 4, orphan: false },
      ],
      edges: [['main', 'helper']],
    }
    const m = callgraphMermaid(g)
    expect(m).toContain('flowchart TD')
    expect(m).toContain('main["main"]')
    expect(m).toContain('nmain --> nhelper')
  })

  it('marks orphans', () => {
    const g = {
      nodes: [{ id: 'unused', name: 'unused', line: 9, orphan: true }],
      edges: [],
    }
    expect(callgraphMermaid(g)).toContain('unused["unused ⚠"]:::orphan')
    expect(callgraphMermaid(g)).toContain('classDef orphan')
  })

  it('escapes quotes in names', () => {
    const g = { nodes: [{ id: 'a', name: 'we"ird', line: 1, orphan: false }], edges: [] }
    expect(callgraphMermaid(g)).not.toContain('we"ird')
  })

  it('returns empty string for null/empty graph', () => {
    expect(callgraphMermaid(null)).toBe('')
    expect(callgraphMermaid({ nodes: [], edges: [] })).toBe('')
  })
})
