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
import { buildDesignDocPrompt } from './designdoc'

const tour = [
  { label: 'run started', ts: 1 },
  { label: 'edit_file → edited src/codingdude/widget.py', ts: 2 },
  { label: 'pytest (gates)', ts: 3 },
  { label: 'run finished', ts: 4 },
]

describe('buildDesignDocPrompt', () => {
  it('builds an ADR-writing prompt from the run narrative', () => {
    const p = buildDesignDocPrompt('fix flaky gate', tour)
    expect(p).toContain('fix flaky gate')
    expect(p).toContain('src/codingdude/widget.py')
    expect(p).toContain('pytest (gates)')
    expect(p).toMatch(/ADR|design document/i)
  })

  it('demands a full ADR structure', () => {
    const p = buildDesignDocPrompt('q', tour)
    for (const section of ['Context', 'Decision', 'Consequences']) {
      expect(p).toContain(section)
    }
  })

  it('returns null without a tour', () => {
    expect(buildDesignDocPrompt('q', [])).toBeNull()
  })
})
