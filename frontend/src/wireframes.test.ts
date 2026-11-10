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
// R85 #314: defensive parse seam for wireframe packs. The backend validator
// (artifacts.py _validate_wireframe) already rejects structural violations at
// emit time; this seam never throws anyway — a truncated or hand-mangled
// payload must render as a readable warning, never a crashed tab.
import { describe, expect, it } from 'vitest'
import { parseWireframe, type WireframeVm } from './wireframes'

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

describe('parseWireframe', () => {
  it('passes a valid pack through intact', () => {
    const vm = parseWireframe(PACK)
    expect(vm.ok).toBe(true)
    expect(vm.problems).toEqual([])
    expect(vm.screens).toEqual(PACK.screens)
    expect(vm.flows).toEqual(PACK.flows)
  })

  it('rejects an unsupported version without rendering screens', () => {
    const vm = parseWireframe({ ...PACK, version: 2 })
    expect(vm.ok).toBe(false)
    expect(vm.screens).toEqual([])
    expect(vm.problems.join(' ')).toMatch(/version/i)
  })

  it('never throws on null, primitives, or garbage', () => {
    for (const bad of [null, undefined, 42, 'pack', [], {}]) {
      const vm: WireframeVm = parseWireframe(bad)
      expect(vm.ok).toBe(false)
      expect(vm.screens).toEqual([])
      expect(vm.flows).toEqual([])
      expect(vm.problems.length).toBeGreaterThan(0)
    }
  })

  it('drops malformed entries instead of crashing', () => {
    const vm = parseWireframe({
      version: 1,
      screens: [null, 7, { id: 'ok', title: 't', template: '', regions: [null, 'x', { name: 'a', widget: 'text', label: 'A', notes: '' }] }],
      flows: [null, { from: 'ok', to: 9, trigger: '', label: '' }, { from: 'ok', to: 'ok', trigger: 'click', label: 'go' }],
    })
    expect(vm.ok).toBe(true)
    expect(vm.screens).toHaveLength(1)
    expect(vm.screens[0].regions).toEqual([{ name: 'a', widget: 'text', label: 'A', notes: '' }])
    expect(vm.flows).toEqual([{ from: 'ok', to: 'ok', trigger: 'click', label: 'go' }])
    expect(vm.problems.join(' ')).toMatch(/dropped/i)
  })

  it('coerces missing fields to empty strings, unknown widgets kept', () => {
    const vm = parseWireframe({ version: 1, screens: [{ id: 's', widget: 'mystery' }], flows: [] })
    expect(vm.ok).toBe(true)
    expect(vm.screens[0]).toEqual({ id: 's', title: '', template: '', regions: [] })
    expect(vm.problems).toEqual([])
  })

  it('reports truncated packs with one problem line, not a stack trace', () => {
    const vm = parseWireframe({ version: 1, screens: 'nope', flows: undefined })
    expect(vm.ok).toBe(true)
    expect(vm.screens).toEqual([])
    expect(vm.problems.join(' ')).toMatch(/no usable screens/i)
  })
})

// Smoke gate: renderToString — react-dom is already a dependency, so the
// component's real DOM output is asserted without adding RTL.
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import { WireframeView } from './WireframeView.jsx'
import { Artifacts } from './panels/dock/Artifacts.jsx'

describe('WireframeView (render smoke)', () => {
  it('renders screens, regions, widget tags, and flows', () => {
    const html = renderToString(createElement(WireframeView, { payload: PACK }))
    expect(html).toContain('Library')
    expect(html).toContain('Header')
    expect(html).toContain('header') // widget tag
    expect(html).toContain('title + search') // notes
    expect(html).toContain('click item') // flow trigger on the map edge
  })

  it('degrades garbage payloads to a warning line', () => {
    const html = renderToString(createElement(WireframeView, { payload: { version: 3 } }))
    expect(html).toMatch(/unsupported wireframe version/i)
    expect(html).not.toContain('Library')
  })

  it('theme prop defaults to lofi; unknown themes render lofi with a note', () => {
    const def = renderToString(createElement(WireframeView, { payload: PACK }))
    expect(def).not.toMatch(/unknown theme/i)
    const odd = renderToString(createElement(WireframeView, { payload: PACK, theme: 'brutal' }))
    expect(odd).toMatch(/unknown theme/i)
    expect(odd).toContain('Library')
  })
})

describe('Artifacts routing (render smoke)', () => {
  const artifact = {
    id: 'w1', kind: 'wireframe', title: 'Pack', status: 'pending', payload: PACK, response: null,
  }
  it('routes kind=wireframe to WireframeView, not the markdown fallback', () => {
    const html = renderToString(createElement(Artifacts, { sessionId: 's', initialItems: [artifact] }))
    expect(html).toContain('Library') // wireframe renderer output
    expect(html).not.toContain('renderer:') // only shows on degradation
  })
})

// R85 #316: click-to-focus — the pure half lives at the seam so the toggle
// table is spec'd independently of the DOM.
import { applyFocus } from './wireframes'

describe('applyFocus', () => {
  it('focuses a screen from no focus', () => {
    expect(applyFocus(null, 's1')).toBe('s1')
  })
  it('re-clicking the focused screen clears focus', () => {
    expect(applyFocus('s1', 's1')).toBeNull()
  })
  it('clicking another screen moves focus', () => {
    expect(applyFocus('s1', 's2')).toBe('s2')
  })
})

describe('WireframeView focus (render smoke)', () => {
  const TWO = {
    version: 1,
    screens: [
      { id: 'a', title: 'Alpha', template: '"x"', regions: [{ name: 'x', widget: 'text', label: 'X', notes: '' }] },
      { id: 'b', title: 'Beta', template: '"y"', regions: [{ name: 'y', widget: 'text', label: 'Y', notes: '' }] },
    ],
    flows: [
      { from: 'a', to: 'b', trigger: 'click', label: 'next' },
      { from: 'b', to: 'a', trigger: 'back', label: '' },
    ],
  }
  it('marks the focused screen and its flows, not the others', () => {
    const html = renderToString(createElement(WireframeView, { payload: TWO, initialFocused: 'a' }))
    expect(html).toMatch(/data-focused="true"[^<]*<[^>]*>|<[^>]*data-focused="true"/)
    expect((html.match(/data-focused="true"/g) ?? []).length).toBe(4) // screen box a + map node a + both edges touching a
    expect(html).toContain('data-screen="b"')
  })
  it('no focus by default', () => {
    const html = renderToString(createElement(WireframeView, { payload: TWO }))
    expect(html).not.toContain('data-focused="true"')
  })
})

// R85 #316 contract (REQ-4): WireframeFlowMap — SVG node-link overview with a
// layered layout, click-to-focus via scrollIntoView. The layout is pure seam.
import { layoutScreens } from './wireframes'
import { WireframeFlowMap } from './wireframes/WireframeFlowMap.jsx'

describe('layoutScreens', () => {
  it('chains layer by layer (columns deepen, rows stack within a layer)', () => {
    const lay = layoutScreens([{ id: 'a' }, { id: 'b' }, { id: 'c' }], [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }])
    expect(lay.layers).toEqual([['a'], ['b'], ['c']])
    expect(lay.pos.a).toEqual({ x: 0, y: 0 })
    expect(lay.pos.c.x).toBeGreaterThan(lay.pos.b.x)
    expect(lay.pos.b.y).toBe(0)
  })
  it('roots share layer 0 in input order (rows stack), consumers follow', () => {
    const lay = layoutScreens([{ id: 'a' }, { id: 'b' }, { id: 'c' }], [{ from: 'a', to: 'c' }, { from: 'b', to: 'c' }])
    expect(lay.layers).toEqual([['a', 'b'], ['c']])
    expect(lay.pos.b.y).toBeGreaterThan(lay.pos.a.y)
    expect(lay.pos.c.x).toBeGreaterThan(lay.pos.a.x)
  })
  it('cycles never hang and lose no screen', () => {
    const lay = layoutScreens([{ id: 'a' }, { id: 'b' }], [{ from: 'a', to: 'b' }, { from: 'b', to: 'a' }])
    expect(lay.layers.flat().sort()).toEqual(['a', 'b'])
  })
  it('empty in, empty out', () => {
    expect(layoutScreens([], []).layers).toEqual([])
  })
})

describe('WireframeFlowMap (render smoke)', () => {
  const MAP = {
    screens: [
      { id: 'a', title: 'Alpha', template: '', regions: [] },
      { id: 'b', title: 'Beta', template: '', regions: [] },
    ],
    flows: [{ from: 'a', to: 'b', trigger: 'click', label: 'next' }],
  }
  it('renders an SVG node for each screen and a labelled edge per flow', () => {
    const html = renderToString(createElement(WireframeFlowMap, { screens: MAP.screens, flows: MAP.flows }))
    expect(html).toContain('<svg')
    expect(html).toContain('data-map-node="a"')
    expect(html).toContain('data-map-node="b"')
    expect(html).toContain('data-map-edge="a:b"')
    expect(html).toContain('click')
  })
  it('marks the focused node and its edges', () => {
    const html = renderToString(createElement(WireframeFlowMap, { screens: MAP.screens, flows: MAP.flows, initialFocused: 'a' }))
    expect((html.match(/data-focused="true"/g) ?? []).length).toBe(2) // node a + edge a->b
  })
})



