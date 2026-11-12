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

// R87 #326: emitted artifacts (html pages, wireframe packs) get a chat card
// with a View deep-link — the #189 bug class again: the Artifacts dock panel
// alone hid them from the conversation.
// @vitest-environment jsdom
import { ARTIFACT_FOCUS_EVENT, emittedArtifacts, requestArtifactFocus, takeArtifactFocusRequest } from './artifacts'
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { EmittedArtifactCard } from './cards/chatCards.jsx'
import { Artifacts } from './panels/dock/Artifacts.jsx'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// jsdom environment notes: (1) fs needs a real path, not a jsdom URL object
// (and Windows /G:/ pathnames need fileURLToPath); (2) jsdom ships no
// EventSource, which the Artifacts panel opens on mount.
const readSrc = (rel: string): string => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8')
class FakeEventSource { close() { /* noop */ } }
const g = globalThis as Record<string, unknown>
if (!g.EventSource) g.EventSource = FakeEventSource

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

  it('never surfaces a dismissed (expired) artifact', () => {
    const out = pendingArtifacts([a('1', 'choice', 'dismissed'), a('2', 'spec')])
    expect(out.map((x) => x.id)).toEqual(['2'])
  })

  it('caps the inline list at 3', () => {
    const out = pendingArtifacts([a('1', 'choice'), a('2', 'spec'), a('3', 'choice'), a('4', 'spec')])
    expect(out).toHaveLength(3)
  })

  it('empty input is empty', () => {
    expect(pendingArtifacts([])).toEqual([])
  })
})

describe('emittedArtifacts (R87-D)', () => {
  it('keeps pending html/wireframe artifacts, drops everything else', () => {
    const out = emittedArtifacts([
      a('1', 'wireframe'),
      a('2', 'html'),
      a('3', 'choice'),
      a('4', 'wireframe', 'answered'),
      a('5', 'wireframe', 'dismissed'),
      a('6', 'qa'),
    ])
    expect(out.map((x) => x.id)).toEqual(['1', '2'])
  })
  it('caps the card list at 3', () => {
    const out = emittedArtifacts([a('1', 'wireframe'), a('2', 'html'), a('3', 'wireframe'), a('4', 'html')])
    expect(out).toHaveLength(3)
  })
  it('exposes the one event name every wiring site shares', () => {
    expect(ARTIFACT_FOCUS_EVENT).toBe('cd-focus-artifact')
  })
})

describe('EmittedArtifactCard (render smoke, R87-D)', () => {
  const items = [
    { id: 'wf1', kind: 'wireframe', title: 'Default layout', status: 'pending', payload: {} },
    { id: 'h1', kind: 'html', title: 'Chart page', status: 'pending', payload: {} },
  ]
  it('renders one read-only row per emitted artifact with a View button', () => {
    const html = renderToString(createElement(EmittedArtifactCard, { items }))
    expect(html).toContain('Default layout')
    expect(html).toContain('Chart page')
    expect((html.match(/data-view-artifact="/g) ?? []).length).toBe(2)
    expect(html).toContain('data-view-artifact="wf1"')
  })
  it('renders nothing when there is nothing emitted', () => {
    expect(renderToString(createElement(EmittedArtifactCard, { items: [] }))).toBe('')
  })
  it('offers dismiss for stale cards, same retire seam as pending cards', () => {
    const html = renderToString(createElement(EmittedArtifactCard, { items }))
    expect((html.match(/data-dismiss-artifact="/g) ?? []).length).toBe(2)
  })
  it('the View button goes through the focus-request helper (static guard)', () => {
    expect(readSrc('./cards/chatCards.jsx')).toContain('requestArtifactFocus(')
  })
  it('Artifacts panel anchors + listens; Workspace activates the panel (static guard)', () => {
    expect(readSrc('./panels/dock/Artifacts.jsx')).toContain('ARTIFACT_FOCUS_EVENT')
    expect(readSrc('./panels/dock/Artifacts.jsx')).toContain('data-artifact=')
    expect(readSrc('./workspace/Workspace.jsx')).toContain('ARTIFACT_FOCUS_EVENT')
  })
})

// R87-D post-review: the View request must survive the Artifacts panel being
// CLOSED at click time — a bare window event is lost while the panel mounts
// (the listener registers after the dispatch completes). The bus holds the id
// until a mounted panel consumes it; the event still drives panel activation.
describe('artifact focus bus (R87-D)', () => {
  it('dispatches a real event with the artifact id as detail', () => {
    const seen: Array<Record<string, unknown>> = []
    const spy = (e: Event) => seen.push((e as CustomEvent).detail)
    window.addEventListener(ARTIFACT_FOCUS_EVENT, spy)
    requestArtifactFocus('wf9')
    window.removeEventListener(ARTIFACT_FOCUS_EVENT, spy)
    expect(seen).toEqual([{ id: 'wf9' }])
  })
  it('holds the request until a panel takes it, then clears', () => {
    requestArtifactFocus('w1')
    expect(takeArtifactFocusRequest()).toBe('w1')
    expect(takeArtifactFocusRequest()).toBeNull()
  })
})

describe('Artifacts focus scroll/ring (R87-D, jsdom)', () => {
  const wf = (id: string) => ({
    id, kind: 'wireframe', title: id, status: 'pending',
    payload: { version: 1, screens: [], flows: [] },
  })
  it('rings and scrolls to the requested artifact on an OPEN panel', async () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    let scrolled = 0
    const root = createRoot(container)
    await act(async () => root.render(createElement(Artifacts, { sessionId: 's', initialItems: [wf('wf1')] })))
    const el = container.querySelector('[data-artifact="wf1"]') as HTMLElement | null
    expect(el).toBeTruthy()
    el!.scrollIntoView = () => { scrolled += 1 }
    await act(async () => requestArtifactFocus('wf1'))
    const ringed = container.querySelector('[data-artifact="wf1"]') as HTMLElement
    expect(ringed.getAttribute('data-focused')).toBe('true')
    expect(ringed.className).toMatch(/border-accent/)
    expect(scrolled).toBe(1)
    await act(async () => root.unmount())
  })
  it('consumes a pending request at mount (panel was CLOSED when View fired)', async () => {
    requestArtifactFocus('wf2') // no panel mounted yet — the bus must hold it
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => root.render(createElement(Artifacts, { sessionId: 's', initialItems: [wf('wf2')] })))
    const ringed = container.querySelector('[data-artifact="wf2"]') as HTMLElement
    expect(ringed.getAttribute('data-focused')).toBe('true')
    expect(ringed.className).toMatch(/border-accent/)
    await act(async () => root.unmount())
  })
})

describe('Artifacts payload-less cards (SSE delta crash class)', () => {
  // The backend once shipped SSE 'emitted'/'answered' deltas as raw DB rows
  // (payload_json instead of a mapped payload). A replaced html card then
  // read a.payload.html of undefined and took down the whole React tree.
  // The panel must degrade to a notice, never crash, for ANY kind.
  const rawRow = (id: string, kind: string): never =>
    ({ id, kind, title: id, status: 'answered', payload_json: '{}' }) as never
  const kinds = ['html', 'qa', 'choice', 'decision', 'spec']
  for (const kind of kinds) {
    it(`renders a notice instead of crashing for a payload-less ${kind} card`, () => {
      const html = renderToString(createElement(Artifacts, {
        sessionId: 's',
        initialItems: [rawRow(`raw-${kind}`, kind)],
      }))
      expect(html).toContain('data-payload-missing')
    })
  }
})
