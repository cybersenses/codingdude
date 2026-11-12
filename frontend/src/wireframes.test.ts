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

  it('drops id-less screens instead of rendering them with an empty id (#320)', () => {
    const vm = parseWireframe({
      version: 1,
      screens: [{ title: 'no id', regions: [] }, PACK.screens[0]],
      flows: [],
    })
    expect(vm.screens.map((s) => s.id)).toEqual(['s1'])
    expect(vm.problems.join(' ')).toMatch(/dropped a screen with no id/)
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
  // R87 #330: the first smoke's v2-internal assertions (widget tags, notes
  // text in the SSR shell) moved to wireframe-view-v3.test.tsx — the shell
  // no longer carries them; region content arrives in the async SVG.
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
  // #320 (REQ-6 inline-edit half): a pending wireframe card offers the DSL
  // editor — the same drafts+save respond seam the spec block uses. SSR smoke
  // asserts presence and pending-gating; the click→respond path reuses the
  // spec editor's handler shape, whose contract is covered backend-side by
  // tests/test_wireframes.py::test_respond_accepts_inline_edits_on_a_wireframe.
  it('offers inline DSL editing on a pending wireframe card', () => {
    const html = renderToString(createElement(Artifacts, { sessionId: 's', initialItems: [artifact] }))
    expect(html).toMatch(/data-wireframe-edit="w1"/)
    expect(html).toMatch(/&quot;version&quot;: 1/) // editor pre-filled with the pretty DSL source
    expect(html).toContain('>save</button>')
  })
  it('hides the editor once the card is answered', () => {
    const answered = { ...artifact, status: 'answered', response: { content: '{}' } }
    const html = renderToString(createElement(Artifacts, { sessionId: 's', initialItems: [answered] }))
    expect(html).not.toContain('data-wireframe-edit')
    expect(html).toContain('Library') // the renderer still shows the pack
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

describe('WireframeView focus (render smoke)', () => {
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
  it('an explicit focused=null clears the map even when inner state holds an id (#320)', () => {
    // The parent cleared focus (focus toggle off); `focused ?? inner` used to
    // resurrect the stale id from the standalone fallback and keep the map marked.
    const html = renderToString(createElement(WireframeFlowMap, { screens: MAP.screens, flows: MAP.flows, focused: null, initialFocused: 'a' }))
    expect(html).not.toContain('data-focused="true"')
  })
  it('standalone use (no focused prop) still owns focus internally', () => {
    const html = renderToString(createElement(WireframeFlowMap, { screens: MAP.screens, flows: MAP.flows, initialFocused: 'b' }))
    expect((html.match(/data-focused="true"/g) ?? []).length).toBe(2) // node b + edge a->b
  })
})

// R87 #325 (REQ-D): the map reads like an overview, not a stub — nodes carry
// the screen's region count, trigger/label move into hover titles (no text
// spam on the canvas), and the arrowhead contract is pinned by test.
describe('WireframeFlowMap v2 (render smoke, R87-C)', () => {
  const V2 = {
    screens: [
      { id: 'a', title: 'Alpha', template: '', regions: [{ name: 'x' }, { name: 'y' }, { name: 'z' }] },
      { id: 'b', title: 'Beta', template: '', regions: [{ name: 'x' }] },
    ],
    flows: [{ from: 'a', to: 'b', trigger: 'click', label: 'next' }],
  }
  it('nodes carry their screen title and region count', () => {
    const html = renderToString(createElement(WireframeFlowMap, { screens: V2.screens, flows: V2.flows }))
    expect(html).toContain('data-map-regions="3"')
    expect(html).toContain('data-map-regions="1"')
    expect(html).toContain('3 regions')
    expect(html).toContain('1 region')
  })
  it('edges keep arrowheads and move trigger/label into a hover title', () => {
    const html = renderToString(createElement(WireframeFlowMap, { screens: V2.screens, flows: V2.flows }))
    expect(html).toContain('<marker')
    expect(html).toMatch(/marker-end="url\(#wfm-arrow\)"/)
    expect(html).toContain('<title>click</title>')
    expect(html).not.toMatch(/<text[^>]*>click</) // no visible trigger text on the canvas
  })
})

// R87 #323 (REQ-A): proportions — authored column/row weights become real fr
// tracks so a wireframe's layout means something. Pure seam, same never-throws
// contract: invalid authored values degrade to an equal split + a problems[]
// entry, never a crash.
import { screenTracks } from './wireframes'

const SHAPE4x3 = '"strip strip strip strip" "nav rail main chat" "nav rail dock composer"'

describe('screenTracks (R87-A proportions)', () => {
  it('maps authored columns onto the template column count as fr tracks', () => {
    const t = screenTracks({ template: SHAPE4x3, columns: [16, 20, 44, 20] })
    expect(t.columns).toBe('16fr 20fr 44fr 20fr')
    expect(t.rows).toBe('1fr 1fr 1fr') // 3 template rows, no authored rows → equal
  })
  it('authored rows are honored as fr tracks too', () => {
    const t = screenTracks({ template: SHAPE4x3, columns: [16, 20, 44, 20], rows: [2, 1, 1] })
    expect(t.rows).toBe('2fr 1fr 1fr')
  })
  it('missing columns/rows fall back to an equal split with no problems', () => {
    const t = screenTracks({ template: SHAPE4x3 })
    expect(t.columns).toBe('1fr 1fr 1fr 1fr')
    expect(t.rows).toBe('1fr 1fr 1fr')
  })
  it('a wrong-length columns list falls back + reports one problem', () => {
    const problems: string[] = []
    const t = screenTracks({ template: SHAPE4x3, columns: [16, 20] }, problems)
    expect(t.columns).toBe('1fr 1fr 1fr 1fr')
    expect(problems.join(' ')).toMatch(/columns/i)
  })
  it('non-positive, non-finite, and non-number entries fall back + report', () => {
    for (const bad of [[0, 20, 44, 20], [-1, 20, 44, 20], [NaN, 20, 44, 20], ['x', 20, 44, 20]]) {
      const problems: string[] = []
      const t = screenTracks({ template: SHAPE4x3, columns: bad as number[] }, problems)
      expect(t.columns).toBe('1fr 1fr 1fr 1fr')
      expect(problems.length).toBe(1)
    }
  })
  it('fractional weights are preserved verbatim', () => {
    const t = screenTracks({ template: SHAPE4x3, columns: [0.16, 0.2, 0.44, 0.2] })
    expect(t.columns).toBe('0.16fr 0.2fr 0.44fr 0.2fr')
  })
  it('no template → empty tracks (regions stack; renderer skips grid styles)', () => {
    const t = screenTracks({ template: '', columns: [1, 2] })
    expect(t.columns).toBe('')
    expect(t.rows).toBe('')
  })
})

describe('parseWireframe carries proportions (R87-A)', () => {
  it('keeps valid authored columns/rows on the screen, no problems', () => {
    const vm = parseWireframe({
      version: 1,
      screens: [{ id: 'p', title: 'P', template: SHAPE4x3, columns: [16, 20, 44, 20], rows: [2, 1, 1], regions: [] }],
      flows: [],
    })
    expect(vm.ok).toBe(true)
    expect(vm.screens[0].columns).toEqual([16, 20, 44, 20])
    expect(vm.screens[0].rows).toEqual([2, 1, 1])
    expect(vm.problems).toEqual([])
  })
  it('drops invalid columns/rows (key absent) + reports, pack still renders', () => {
    const vm = parseWireframe({
      version: 1,
      screens: [{ id: 'p', title: 'P', template: '"a"', columns: ['x'], rows: [0], regions: [] }],
      flows: [],
    })
    expect(vm.ok).toBe(true)
    expect(vm.screens[0]).not.toHaveProperty('columns')
    expect(vm.screens[0]).not.toHaveProperty('rows')
    expect(vm.problems.join(' ')).toMatch(/dropped/i)
  })
  it('absent columns/rows stay absent (old packs keep their shape)', () => {
    const vm = parseWireframe({ version: 1, screens: [{ id: 's', title: 't', template: '', regions: [] }], flows: [] })
    expect(vm.screens[0]).toEqual({ id: 's', title: 't', template: '', regions: [] })
  })
})

// R87 #330: the v2 renderer smoke describe (glyph internals, fr-track grid
// styles, notes-as-hover-text) moved to wireframe-view-v3.test.tsx — its
// assertions described the replaced v2 implementation, so the adapted v3
// contract lives beside the v3 renderer tests instead of here.

// R85 #317 (REQ-7): per-screen implement button — prefills the composer via
// the exported store setter.
describe('WireframeView implement handoff (render smoke)', () => {
  it('renders an implement button per screen carrying screen + pack identity', () => {
    const html = renderToString(createElement(WireframeView, { payload: TWO, pack: { title: 'Admin pack', id: 'wf_9' } }))
    expect((html.match(/data-implement="/g) ?? []).length).toBe(2) // one per screen
    expect(html).toContain('data-implement="a"')
    expect(html).toContain('data-implement="b"')
  })
})




