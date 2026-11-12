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
// R87 #330: v3 view contract — the tests whose assertions described the
// replaced v2 internals (glyph data-glyphs, grid-template fr tracks, notes
// as hover text) live HERE, not in wireframes.test.ts, so that file's
// surviving tests stay byte-identical to the pre-#330 state (deletions
// only there; this file carries the adapted coverage). The hooks-invariant
// guard moves with them: its bail matcher must match the JSX-returning
// bail, not the scroll effect's inner `if (!vm.ok) return` guard —
// hook-internal conditionals are legal; the invariant is that every hook
// call precedes the component's bail.
import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { WireframeView } from './WireframeView.jsx'

const PACK = {
  version: 1,
  screens: [
    {
      id: 's1',
      title: 'Library',
      template: '"nav header" "list main"',
      regions: [
        { name: 'nav', widget: 'nav', label: 'Nav', notes: '' },
        { name: 'header', widget: 'header', label: 'Header', notes: 'title + search' },
        { name: 'list', widget: 'list', label: 'Items', notes: '' },
        { name: 'main', widget: 'text', label: 'Detail', notes: 'selected item' },
      ],
    },
  ],
  flows: [{ from: 's1', to: 's1', trigger: 'click item', label: 'open detail' }],
}

describe('WireframeView v3 (render smoke, R87 #330)', () => {
  const FRAME_PACK = {
    version: 1,
    screens: [
      {
        id: 'w',
        title: 'Workspace',
        template: '"strip strip strip strip" "nav rail main chat" "nav rail dock composer"',
        columns: [16, 20, 44, 20],
        rows: [2, 1, 1],
        regions: [
          { name: 'strip', widget: 'header', label: 'Strip', notes: 'status band' },
          { name: 'nav', widget: 'nav', label: 'Nav', notes: '' },
          { name: 'rail', widget: 'list', label: 'Rail', notes: '' },
          { name: 'main', widget: 'code', label: 'Main', notes: '' },
          { name: 'dock', widget: 'table', label: 'Dock', notes: '' },
          { name: 'chat', widget: 'text', label: 'Chat', notes: '' },
          { name: 'composer', widget: 'form', label: 'Composer', notes: '' },
        ],
      },
    ],
    flows: [{ from: 'w', to: 'w', trigger: 'click', label: 'loop' }],
  }

  it('renders the screen title, its canvas box, and the flow trigger', () => {
    const html = renderToString(createElement(WireframeView, { payload: PACK }))
    expect(html).toContain('Library')
    expect(html).toContain('data-screen="s1"')
    expect(html).toContain('click item') // flow trigger on the map edge
    // v3: region content lives inside the asynchronously rendered wireloom
    // SVG — the SSR shell carries only the frame, so no glyph internals.
    expect(html).toContain('data-wireloom-pending="s1"')
    expect(html).not.toContain('data-glyph=')
  })
  it('frames each screen as a fixed 16:10 canvas with a title bar', () => {
    const html = renderToString(createElement(WireframeView, { payload: FRAME_PACK }))
    expect(html).toMatch(/aspect-ratio:16\s*\/\s*10/)
    expect(html).toMatch(/data-screen-title="Workspace"/)
  })
  it('shows one pending placeholder per screen before the SVG lands', () => {
    const html = renderToString(createElement(WireframeView, { payload: FRAME_PACK }))
    expect(html).toContain('data-wireloom-pending="w"')
    expect(html).not.toContain('data-glyph=') // Sketch glyphs are gone in v3
    expect(html).not.toContain('data-wireloom-svg')
  })
  it('keeps notes out of the shell — they ride the SVG annotations', () => {
    const html = renderToString(createElement(WireframeView, { payload: FRAME_PACK }))
    expect(html).not.toMatch(/<div[^>]*>status band/) // no notes block in the body
  })
  it('renders the flow map after the screen canvases', () => {
    const html = renderToString(createElement(WireframeView, { payload: FRAME_PACK }))
    expect(html.indexOf('data-screen="w"')).toBeGreaterThan(-1)
    expect(html.indexOf('flow map')).toBeGreaterThan(html.indexOf('data-screen="w"'))
  })
})

// #320 (review blocker): hooks must run unconditionally — the `if (!vm.ok)`
// early return may sit AFTER every hook call but never between hook groups,
// or a mounted instance flipping valid<->invalid changes hook count and
// React crashes (#310 class; ModelsConfig.jsx documents the invariant). The
// suite is SSR-smoke (no DOM rerender) and there is no react-hooks eslint
// plugin, so this static ordering test is the guard: it fails while any hook
// call sits after the bail.
describe('WireframeView hooks invariant (#320)', () => {
  it('every hook call precedes the vm.ok early return', () => {
    const src = readFileSync(new URL('./WireframeView.jsx', import.meta.url), 'utf8')
    const body = src.slice(src.indexOf('export function WireframeView'))
    const earlyReturn = body.indexOf('if (!vm.ok) {\n    return')
    expect(earlyReturn).toBeGreaterThan(-1)
    for (const hook of ['useState(', 'useRef(', 'useEffect(']) {
      const at = body.lastIndexOf(hook)
      expect(at).toBeGreaterThan(-1)
      expect(at).toBeLessThan(earlyReturn)
    }
  })
})
