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
