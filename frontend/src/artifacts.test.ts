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
import { pendingArtifacts } from './artifacts'

const a = (id: string, kind: string, status = 'pending'): never =>
  ({ id, kind, status, title: id, payload: {} }) as never

describe('pendingArtifacts (#189)', () => {
  it('keeps pending choice/spec artifacts only', () => {
    const out = pendingArtifacts([
      a('1', 'choice'),
      a('2', 'choice', 'answered'),
      a('3', 'html'),
      a('4', 'spec'),
      a('5', 'qa'),
    ])
    expect(out.map((x) => x.id)).toEqual(['1', '4'])
  })

  it('caps the inline list at 3', () => {
    const out = pendingArtifacts([a('1', 'choice'), a('2', 'spec'), a('3', 'choice'), a('4', 'spec')])
    expect(out).toHaveLength(3)
  })

  it('empty input is empty', () => {
    expect(pendingArtifacts([])).toEqual([])
  })
})
