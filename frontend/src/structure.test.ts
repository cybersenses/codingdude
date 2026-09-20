import { describe, expect, it } from 'vitest'

import { structureRows } from './structure'

describe('structureRows', () => {
  it('flattens files+symbols into renderable rows', () => {
    const rows = structureRows({
      files: [
        {
          path: 'src/m.py',
          lines: 10,
          symbols: [
            { kind: 'class', name: 'A', line: 1 },
            { kind: 'function', name: 'top', line: 4 },
          ],
        },
      ],
    })
    expect(rows).toEqual([
      { path: 'src/m.py', lines: 10, kind: 'class', name: 'A' },
      { path: 'src/m.py', lines: 10, kind: 'function', name: 'top' },
    ])
  })

  it('handles missing files and symbols defensively', () => {
    expect(structureRows(undefined)).toEqual([])
    expect(structureRows({ files: [{ path: 'x.js' }] })).toEqual([
      { path: 'x.js', lines: undefined, kind: undefined, name: undefined },
    ])
  })
})
