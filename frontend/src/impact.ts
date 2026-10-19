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
// #86 (R38 phase 3): build a Mermaid flowchart of the edited-file impact
// graph returned by the server (/diff → impact). Pure module, unit-tested.

export interface ImpactEdge {
  path: string
  dependents: string[]
}

export interface ImpactGraph {
  edges: ImpactEdge[]
  orphans: string[]
}

/** Mermaid node id safe across slashes/dots. */
export function nodeId(path: string): string {
  return 'n' + path.replace(/[^A-Za-z0-9]/g, '_')
}

/** Escape a label for Mermaid ("..." quoting). */
function label(path: string): string {
  return path.replace(/"/g, '#quot;')
}

/** Full flowchart source; changed files are 'changed'-class diamonds,
 * dependents plain boxes. Isolated changed files get a note edge so they
 * still render. Empty string when there is nothing to draw. */
export function impactMermaid(impact: ImpactGraph | null): string {
  if (!impact || !impact.edges.length) return ''
  const lines: string[] = [
    'flowchart LR',
    'classDef changed fill:#7c3aed,stroke:#a78bfa,color:#fff',
  ]
  const declared = new Set<string>()
  for (const e of impact.edges) {
    const id = nodeId(e.path)
    if (!declared.has(id)) {
      lines.push(`  ${id}(["${label(e.path)}"]):::changed`)
      declared.add(id)
    }
    for (const dep of e.dependents) {
      const did = nodeId(dep)
      if (!declared.has(did)) {
        lines.push(`  ${did}["${label(dep)}"]`)
        declared.add(did)
      }
      lines.push(`  ${did} --> ${id}`)
    }
  }
  for (const o of impact.orphans) {
    const id = nodeId(o)
    if (!declared.has(id)) {
      lines.push(`  ${id}(["${label(o)}"]):::changed`)
      declared.add(id)
    }
  }
  return lines.join('\n')
}
