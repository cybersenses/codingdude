// CodingDude — a personal coding agent.
// Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
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
import { parseCitationHref, parseRevealArgs, rehypeCitations } from './citations'

describe('parseRevealArgs (TOOL_CALL_START payload)', () => {
  it('parses a JSON string with the full range', () => {
    expect(parseRevealArgs('{"path":"src/app.py","start_line":3,"end_line":9}'))
      .toEqual({ path: 'src/app.py', start: 3, end: 9 })
  })

  it('defaults end to start and floors/clamps lines', () => {
    expect(parseRevealArgs({ path: 'a.ts', start_line: 5 }))
      .toEqual({ path: 'a.ts', start: 5, end: 5 })
    expect(parseRevealArgs({ path: 'a.ts', start_line: 0 }))
      .toEqual({ path: 'a.ts', start: 1, end: 1 })
  })

  it('swaps a reversed range', () => {
    expect(parseRevealArgs({ path: 'a.ts', start_line: 9, end_line: 3 }))
      .toEqual({ path: 'a.ts', start: 3, end: 9 })
  })

  it('returns null for malformed input instead of throwing', () => {
    expect(parseRevealArgs('not json')).toBeNull()
    expect(parseRevealArgs(null)).toBeNull()
    expect(parseRevealArgs({})).toBeNull()
    expect(parseRevealArgs({ path: 'a.py' })).toBeNull()
    expect(parseRevealArgs({ path: 'a.py', start_line: 'x' })).toBeNull()
    expect(parseRevealArgs({ path: 'a.py', start_line: 1, end_line: 'y' })).toBeNull()
  })
})

describe('cdopen href round-trip', () => {
  it('round-trips a citation through href and back', () => {
    const href = 'cdopen://' + encodeURIComponent('src/panels/Editor.jsx') + '?start=24&end=31'
    expect(parseCitationHref(href)).toEqual({ path: 'src/panels/Editor.jsx', start: 24, end: 31 })
  })

  it('rejects non-cdopen, empty and broken hrefs', () => {
    expect(parseCitationHref('https://example.com')).toBeNull()
    expect(parseCitationHref('cdopen://')).toBeNull()
    expect(parseCitationHref('cdopen://%zz')).toBeNull()
  })
})

describe('rehypeCitations', () => {
  const transform = rehypeCitations()

  it('turns citations in prose text into cdopen anchors', () => {
    const tree = { type: 'root', children: [
      { type: 'text', value: 'the fix lives in src/app.py:12 — see it' },
    ] }
    const out: any = transform(tree as any)
    expect(out.children[0].value).toBe('the fix lives in ')
    const a = out.children[1]
    expect(a.tagName).toBe('a')
    expect(a.properties.href).toBe('cdopen://src%2Fapp.py?start=12&end=12')
    expect(a.children[0].value).toBe('src/app.py:12')
    expect(out.children[2].value).toBe(' — see it')
  })

  it('keeps ranges and skips code, pre and existing links', () => {
    const tree = { type: 'root', children: [
      { type: 'element', tagName: 'code', children: [
        { type: 'text', value: 'src/app.py:12' },
      ] },
      { type: 'element', tagName: 'a', properties: { href: 'x' }, children: [
        { type: 'text', value: 'src/app.py:12' },
      ] },
      { type: 'element', tagName: 'p', children: [
        { type: 'text', value: 'range at deep/note.md:3-9 here' },
      ] },
    ] }
    const out: any = transform(tree as any)
    expect(out.children[0].children[0].type).toBe('text') // code untouched
    expect(out.children[1].children[0].type).toBe('text') // link untouched
    const p = out.children[2].children
    expect(p[0].value).toBe('range at ')
    expect(p[1].properties.href).toBe('cdopen://deep%2Fnote.md?start=3&end=9')
    expect(p[2].value).toBe(' here')
  })

  it('does not touch times or bare prose', () => {
    const tree = { type: 'root', children: [
      { type: 'text', value: 'at 10:30 the note: 1 said so' },
    ] }
    const out: any = transform(tree as any)
    expect(out.children[0].type).toBe('text')
    expect(out.children[0].value).toBe('at 10:30 the note: 1 said so')
  })
})
