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
import { describe, expect, it } from 'vitest'
import { impactMermaid, nodeId } from './impact'

describe('nodeId', () => {
  it('strips unsafe characters', () => {
    expect(nodeId('src/a b.py')).toBe('nsrc_a_b_py')
  })
})

describe('impactMermaid', () => {
  it('returns empty for null or empty input', () => {
    expect(impactMermaid(null)).toBe('')
    expect(impactMermaid({ edges: [], orphans: [] })).toBe('')
  })

  it('declares changed nodes and dependent edges', () => {
    const out = impactMermaid({
      edges: [{ path: 'core.py', dependents: ['user.py', 'app.py'] }],
      orphans: [],
    })
    expect(out).toContain('ncore_py(["core.py"]):::changed')
    expect(out).toContain('nuser_py["user.py"]')
    expect(out).toContain('nuser_py --> ncore_py')
    expect(out).toContain('napp_py --> ncore_py')
  })

  it('still renders orphan (no-dependents) changed files', () => {
    const out = impactMermaid({
      edges: [{ path: 'lonely.py', dependents: [] }],
      orphans: ['lonely.py'],
    })
    expect(out).toContain('nlonely_py(["lonely.py"]):::changed')
    expect(out).not.toContain('-->')
  })

  it('declares each node once', () => {
    const out = impactMermaid({
      edges: [
        { path: 'a.py', dependents: ['c.py'] },
        { path: 'b.py', dependents: ['c.py'] },
      ],
      orphans: [],
    })
    expect(out.match(/nc_py\[/g)).toHaveLength(1)
  })
})
