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
