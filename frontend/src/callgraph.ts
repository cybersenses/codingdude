// #94 (R42): render a file's call graph as a Mermaid flowchart so a human
// can read the structure of agent-generated code. Orphans (no in/out edges)
// are flagged with ⚠ and a distinct class.
export interface CallGraphNode {
  id: string
  name: string
  line: number
  orphan: boolean
}

export interface CallGraph {
  nodes: CallGraphNode[]
  edges: string[][]
}

/** Mermaid node id safe across quotes/specials. */
const nid = (s: string): string => `n${s.replace(/[^A-Za-z0-9_]/g, '_')}`

const esc = (s: string): string => s.replace(/"/g, '#quot;')

export function callgraphMermaid(graph: CallGraph | null): string {
  if (!graph || graph.nodes.length === 0) return ''
  const lines = ['flowchart TD']
  for (const n of graph.nodes) {
    const label = n.orphan ? `${esc(n.name)} ⚠` : esc(n.name)
    lines.push(`    ${nid(n.id)}["${label}"]${n.orphan ? ':::orphan' : ''}`)
  }
  for (const [a, b] of graph.edges) lines.push(`    ${nid(a)} --> ${nid(b)}`)
  lines.push('    classDef orphan stroke:#f59e0b,stroke-dasharray: 4 4')
  return lines.join('\n')
}
