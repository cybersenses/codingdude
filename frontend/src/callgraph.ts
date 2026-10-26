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

export type GraphView =
  | { kind: 'graph' }
  | { kind: 'loading' }
  | { kind: 'empty' }
  | { kind: 'error'; error: string }

/** #99: which state the Graph tab is in. An error (e.g. a 422 from an
 * unparseable file) must surface verbatim — never masquerade as
 * "no callable symbols found". */
export function graphView(
  graph: CallGraph | undefined,
  callgraphPath: string | undefined,
  activePath: string,
  error?: string,
): GraphView {
  if (error) return { kind: 'error', error }
  if (!hasGraphFor(graph, callgraphPath, activePath)) return { kind: 'loading' }
  if (graph.nodes.length === 0) return { kind: 'empty' }
  return { kind: 'graph' }
}

/** True when the stored callgraph belongs to activePath and a fetch
 * succeeded for it — i.e. a transient poll failure must not blank what is
 * rendered (R59 P4 round 6). Lives here, beside graphView and free of
 * React, so the panel's error guard is unit-testable. */
export function hasGraphFor(
  graph: CallGraph | undefined,
  callgraphPath: string | undefined,
  activePath: string,
): boolean {
  return !!graph && callgraphPath === activePath
}
