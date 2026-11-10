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
    expect(html).toContain('open detail') // flow label
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

