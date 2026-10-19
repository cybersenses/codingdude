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
// #154 (R46): render a function's control-flow graph as a Mermaid flowchart.
// Green = reachable block, red = dead/unreachable block — the human sees
// execution paths and dead code at a glance, same Graph tab as the call graph.
export interface CfgBlock {
  id: number
  lines: string[]
  reachable: boolean
}

export interface CfgEdge {
  src: number
  dst: number
  kind: string
}

export interface Cfg {
  function: string
  blocks: CfgBlock[]
  edges: CfgEdge[]
}

const esc = (s: string): string => s.replace(/"/g, '#quot;')

export function cfgMermaid(cfg: Cfg | null): string {
  if (!cfg || cfg.blocks.length === 0) return ''
  const lines = ['flowchart TD']
  for (const b of cfg.blocks) {
    const label = esc(b.lines.slice(0, 4).join('\n') || '(empty)')
    const fill = b.reachable ? '#22c55e' : '#ef4444'
    lines.push(`    B${b.id}["${label}"]`)
    lines.push(`    style B${b.id} fill:${fill},color:#111`)
  }
  for (const e of cfg.edges) {
    lines.push(`    B${e.src} -->|${e.kind}| B${e.dst}`)
  }
  return lines.join('\n')
}
