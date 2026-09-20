import { describe, expect, it } from 'vitest'

import { callgraphMermaid, graphView } from './callgraph'

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

describe('graphView', () => {
  const graph = { nodes: [{ id: 'a', name: 'a', line: 1, orphan: false }], edges: [] }

  it('renders a fresh graph', () => {
    expect(graphView(graph, 'm.py', 'm.py')).toEqual({ kind: 'graph' })
  })

  it('shows stale data as loading, not empty', () => {
    expect(graphView(graph, 'old.py', 'm.py').kind).toBe('loading')
  })

  it('empty graph without error says no symbols', () => {
    const v = graphView({ nodes: [], edges: [] }, 'm.py', 'm.py')
    expect(v).toEqual({ kind: 'empty' })
  })

  it('error beats everything: the message must reach the user', () => {
    const v = graphView(undefined, 'm.py', 'm.py', 'cannot analyze m.py: bad utf-8')
    expect(v).toEqual({ kind: 'error', error: 'cannot analyze m.py: bad utf-8' })
  })
})
