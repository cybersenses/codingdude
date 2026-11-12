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
// R87 #329: wireloom-adapter tests — the compileScreen total-function contract
// (RED) and the renderScreen async wrapper against a mocked wireloom.
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { WireframeScreen } from './wireframes'

vi.mock('wireloom', () => ({
  render: vi.fn(async () => ({ svg: '<svg viewBox="0 0 10 10"></svg>' })),
}))

import { compileScreen, renderScreen } from './wireloom-adapter'

const region = (over: Partial<WireframeScreen['regions'][number]> = {}) => ({
  name: 'main', widget: 'text', label: 'Main', notes: '', ...over,
})

const screen = (over: Partial<WireframeScreen> = {}): WireframeScreen => ({
  id: 'ws', title: 'Workspace', template: '',
  regions: [region()], ...over,
})

afterEach(() => vi.clearAllMocks())

describe('compileScreen — widget mapping', () => {
  it('header maps to a bold large-title line (wireloom header is window chrome only)', () => {
    const src = compileScreen(screen({ regions: [region({ widget: 'header', label: 'Top bar' })] }), [])
    expect(src).toContain('text "Top bar" bold size=large')
    expect(src).not.toMatch(/^\s+header:/m)
  })

  it('nav maps to a list of slots with the label', () => {
    const src = compileScreen(screen({ regions: [region({ widget: 'nav', label: 'Rail' })] }), [])
    expect(src).toContain('list:')
    expect(src).toMatch(/slot "Rail"/)
  })

  it('form maps to inputs and a primary button', () => {
    const src = compileScreen(screen({ regions: [region({ widget: 'form', label: 'Credentials' })] }), [])
    expect(src).toMatch(/input placeholder="Credentials"/)
    expect(src).toContain('button "Credentials" primary')
  })

  it('table composes a grid of cells', () => {
    const src = compileScreen(screen({ regions: [region({ widget: 'table', label: 'Rows' })] }), [])
    expect(src).toMatch(/grid cols=\d+ rows=\d+:/)
    expect(src).toMatch(/cell "/)
  })

  it('list maps to slots including the label row', () => {
    const src = compileScreen(screen({ regions: [region({ widget: 'list', label: 'Inbox' })] }), [])
    expect(src).toContain('list:')
    expect(src).toMatch(/slot "Inbox"/)
  })

  it('chart and image map to their bare leaves', () => {
    const chart = compileScreen(screen({ regions: [region({ widget: 'chart', label: 'Trend' })] }), [])
    expect(chart).toMatch(/^\s+chart$/m)
    const image = compileScreen(screen({ regions: [region({ widget: 'image', label: 'Hero' })] }), [])
    expect(image).toMatch(/^\s+image$/m)
  })

  it('actions maps to a right-aligned button row', () => {
    const src = compileScreen(screen({ regions: [region({ widget: 'actions', label: 'Save' })] }), [])
    expect(src).toMatch(/row justify=end:/)
    expect(src).toContain('button "Save" primary')
  })

  it('tabs maps to a tabs container with the label tab', () => {
    const src = compileScreen(screen({ regions: [region({ widget: 'tabs', label: 'General' })] }), [])
    expect(src).toContain('tabs:')
    expect(src).toMatch(/tab "General"/)
  })

  it('code maps to muted monospace-ish text lines', () => {
    const src = compileScreen(screen({ regions: [region({ widget: 'code', label: 'patch.diff' })] }), [])
    expect(src).toContain('text "patch.diff" bold')
    expect(src).toMatch(/text "···/m)
  })

  it('text maps to the label plus muted notes line', () => {
    const src = compileScreen(screen({
      regions: [region({ widget: 'text', label: 'Summary', notes: 'explains the change' })],
    }), [])
    expect(src).toContain('text "Summary"')
    expect(src).toContain('text "explains the change" muted')
  })

  it('placeholder and unknown widgets both fall back to a slot', () => {
    const ph = compileScreen(screen({ regions: [region({ widget: 'placeholder', label: 'Empty' })] }), [])
    expect(ph).toMatch(/slot "Empty"/)
    const unk = compileScreen(screen({ regions: [region({ widget: 'mystery', name: 'side', label: '' })] }), [])
    expect(unk).toMatch(/slot "side"/)
  })
})

describe('compileScreen — layout', () => {
  it('framed screens emit one row band per template row, regions in their band', () => {
    const s = screen({
      template: '"nav header" "nav main"',
      regions: [
        region({ name: 'nav', widget: 'nav', label: 'Nav' }),
        region({ name: 'header', widget: 'header', label: 'Top' }),
        region({ name: 'main', widget: 'text', label: 'Body' }),
      ],
    })
    const src = compileScreen(s, [])
    expect(src).toContain('row:')
    expect(src.indexOf('list:')).toBeLessThan(src.indexOf('text "Top"'))
    expect(src.indexOf('text "Body"')).toBeGreaterThan(src.indexOf('text "Top"'))
  })

  it('equal or absent weights emit fill columns; unequal emit proportional px', () => {
    const fills = screen({ template: '"a b"', regions: [region({ name: 'a' }), region({ name: 'b' })] })
    expect(compileScreen(fills, [])).toMatch(/col fill:\n {6}section/)
    const wide = screen({
      template: '"a b"', columns: [2, 1],
      regions: [region({ name: 'a' }), region({ name: 'b' })],
    })
    expect(compileScreen(wide, [])).toContain('col 480:')
    expect(compileScreen(wide, [])).toContain('col fill:')
  })

  it('stacked screens (template empty) emit sections without row bands', () => {
    const src = compileScreen(screen({ regions: [region({ label: 'Only' })] }), [])
    expect(src).not.toContain('row:')
    expect(src).toContain('section "Only"')
  })

  it('every compiled source starts with a window and is deterministic', () => {
    const s = screen({ template: '"a"', regions: [region({ name: 'a', widget: 'chart' })] })
    expect(compileScreen(s, []).startsWith('window "Workspace":')).toBe(true)
    expect(compileScreen(s, [])).toBe(compileScreen(s, []))
  })
})

describe('compileScreen — notes and sanitization', () => {
  it('region notes become a window-sibling annotation targeting the region id', () => {
    const src = compileScreen(screen({
      regions: [region({ name: 'nav', widget: 'nav', label: 'Nav', notes: 'five items max' })],
    }), [])
    expect(src).toContain('id="wf-ws-nav"')
    expect(src).toContain('annotation "five items max" target="wf-ws-nav"')
  })

  it('quotes and newlines in labels/notes are sanitized into the source', () => {
    const src = compileScreen(screen({
      regions: [region({ label: 'say "hi"', notes: 'line1\nline2' })],
    }), [])
    expect(src).not.toMatch(/text "say " hi"/)
    expect(src).toContain('annotation "line1\\nline2"')
    expect(src).not.toMatch(/"line1\nline2"/)
  })

  it('no notes means no annotation', () => {
    const src = compileScreen(screen({ regions: [region({ notes: '' })] }), [])
    expect(src).not.toContain('annotation')
  })
})

describe('compileScreen — totality', () => {
  it('compiles any parse-valid screen without throwing, always yielding a window', () => {
    const widgets = ['nav', 'header', 'form', 'table', 'list', 'text', 'chart', 'actions', 'tabs', 'image', 'code', 'placeholder', 'mystery', '']
    const templates = ['', '"a"', '"a b" "c ."']
    for (const widget of widgets) {
      for (const template of templates) {
        const s = screen({
          title: '', template,
          columns: template ? [1, 2] : undefined,
          regions: [
            region({ name: 'a', widget, label: '', notes: '' }),
            region({ name: 'b', widget, label: 'B', notes: 'note' }),
            region({ name: 'c', widget, label: 'C' }),
          ],
        })
        const src = compileScreen(s, [])
        expect(src.startsWith('window ')).toBe(true)
      }
    }
  })

  it('a screen with zero regions still compiles to a non-empty window', () => {
    const src = compileScreen(screen({ regions: [] }), [])
    expect(src.startsWith('window "Workspace":')).toBe(true)
    expect(src.trim().split('\n').length).toBeGreaterThan(1)
  })
})

describe('renderScreen — async wrapper', () => {
  it('resolves with the svg from wireloom render', async () => {
    const { render } = await import('wireloom')
    const out = await renderScreen('id1', 'window "T":', 'dark')
    expect(out.svg).toBe('<svg viewBox="0 0 10 10"></svg>')
    expect(out.problem).toBeNull()
    expect(render).toHaveBeenCalledWith('id1', 'window "T":', { theme: 'dark' })
  })

  it('returns a problem instead of throwing when wireloom rejects', async () => {
    const { render } = await import('wireloom')
    ;(render as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('Line 2, col 3: unknown primitive'))
    const out = await renderScreen('id2', 'bogus', 'dark')
    expect(out.svg).toBeNull()
    expect(out.problem).toContain('Line 2, col 3')
  })
})
