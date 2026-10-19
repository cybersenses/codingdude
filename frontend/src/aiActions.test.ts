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
import { ACTIONS, buildActionPrompt } from './aiActions'

describe('ACTIONS', () => {
  it('exposes id+label for the standard set', () => {
    expect(ACTIONS.map((a) => a.id)).toEqual(['explain', 'fix', 'optimise', 'improve'])
    expect(ACTIONS.every((a) => a.label.length > 0 && a.directive.length > 0)).toBe(true)
  })
})

describe('buildActionPrompt', () => {
  const code = 'const x = 1\nfoo(x)'

  it('embeds action directive, file path and the selected code verbatim', () => {
    const p = buildActionPrompt('explain', 'src/app.py', code)
    expect(p).toContain('Explain')
    expect(p).toContain('src/app.py')
    expect(p).toContain(code)
  })

  it('uses a distinct directive per action', () => {
    const prompts = ACTIONS.map((a) => buildActionPrompt(a.id, 'f.py', code))
    expect(new Set(prompts).size).toBe(ACTIONS.length)
  })

  it('returns null when selection is empty/whitespace', () => {
    expect(buildActionPrompt('fix', 'f.py', '   \n  ')).toBeNull()
  })

  it('trims surrounding blank lines but preserves inner indentation', () => {
    const p = buildActionPrompt('fix', 'f.py', '\n\n  keep_indent()\n\n')
    expect(p).toContain('  keep_indent()')
    expect(p.startsWith('\n')).toBe(false)
  })
})
