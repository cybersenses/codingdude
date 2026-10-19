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
