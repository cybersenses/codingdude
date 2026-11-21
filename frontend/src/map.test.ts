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
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import { MapView, mapSrc } from './panels/dock/Map.jsx'

// R103 #377: the map is the one surface in this app that runs third-party
// script, so its sandbox is the whole point of giving it its own panel. Two
// properties are pinned here:
//
//   1. scripts are allowed (`allow-scripts`) — otherwise floorplan's page is a
//      blank rectangle, which is why it could not live in the Artifacts viewer;
//   2. same-origin is NOT — without it the frame gets an opaque origin and
//      cannot reach this app's DOM, localStorage or session cookie.
//
// A future "just add allow-same-origin so a fetch works" edit fails test 2.

const MAP_PAGE = '/home/.codingdude/maps/proj-1a2b3c4d/index.html'

const BUILT = {
  built: true,
  reason: '',
  path: MAP_PAGE,
  bytes: 2611097,
  built_at: '2026-11-20T19:00:00+00:00',
}

const ABSENT = {
  built: false,
  reason: `no map has been built for this project yet: expected ${MAP_PAGE}`,
  path: null,
  bytes: 0,
  built_at: null,
  available: true,
  detail: 'node v22.23.2 · floorplan C:/floorplan',
  running: false,
  build: null,
}

// #379: nothing could build this map, so the reason is a dependency, not a
// missing page — a different person has to fix it.
const UNBUILDABLE = {
  ...ABSENT,
  available: false,
  detail: 'node is not on PATH - floorplan needs Node 18 or newer',
  reason: 'no map, and there is nothing to build it with: node is not on PATH',
}

const FAILED = {
  ...ABSENT,
  build: {
    ok: false,
    error: 'floorplan build failed (exit 1): no node nodes',
    warnings: ['node "gates" path "src/x.py" matches no included file'],
    counts: {},
  },
}

function render(state, nonce = 0, extra = {}) {
  return renderToString(
    createElement(MapView, {
      sessionId: 's-1',
      state,
      nonce,
      onRefresh: () => {},
      onBuild: () => {},
      ...extra,
    }),
  )
}

describe('Map panel', () => {
  it('runs the page with scripts but never with same-origin', () => {
    const html = render(BUILT)
    expect(html).toContain('sandbox="allow-scripts"')
    expect(html).not.toContain('allow-same-origin')
  })

  it('points the frame at the served page for this session', () => {
    expect(render(BUILT)).toContain(`src="${mapSrc('s-1')}?v=0"`)
  })

  it('reloads the frame on refresh rather than showing stale bytes', () => {
    expect(render(BUILT, 3)).toContain(`src="${mapSrc('s-1')}?v=3"`)
  })

  it('names why there is nothing to show instead of rendering a blank frame', () => {
    const html = render(ABSENT)
    // The reason names the path it looked in: the config home's map dir since
    // decision #107, not the project root the fixtures used to model.
    expect(html).toContain(MAP_PAGE)
    expect(html).not.toContain('<iframe')
  })

  it('says it is still checking before the first reply', () => {
    expect(render(null)).toContain('checking for a map')
  })

  // #379: the empty state used to offer only "Check again", which re-asked a
  // question whose answer could not change. Building is the action that can.
  it('offers to build the map when it can be built', () => {
    const html = render(ABSENT)
    expect(html).toContain('data-map="build"')
    expect(html).toContain('Check again')
    // `disabled=""` is how React SSR renders the attribute; the Tailwind
    // `disabled:` variant in the class list is not a disabled control.
    expect(html).not.toContain('disabled=""')
  })

  it('does not offer a build when there is nothing to build with', () => {
    // A disabled button here would still read as "click me later"; the
    // dependency has to be installed, so the detail is what is shown.
    const html = render(UNBUILDABLE)
    expect(html).not.toContain('data-map="build"')
    expect(html).toContain('node is not on PATH')
  })

  it('disables the build while it is running so it cannot be started twice', () => {
    // `posting` covers the request in flight; `running` covers a build another
    // tab started. Either way the button is not clickable.
    const notPosting = render(ABSENT, 0, { posting: true })
    expect(notPosting).toContain('disabled=""')
    expect(notPosting).toContain('building')

    const runningElsewhere = render({ ...ABSENT, running: true })
    expect(runningElsewhere).toContain('disabled=""')
  })

  it('shows the failing build receipt verbatim rather than a generic message', () => {
    const html = render(FAILED)
    expect(html).toContain('floorplan build failed (exit 1): no node nodes')
  })

  it('shows the build warnings, which are the only signal that an input was wrong', () => {
    const html = render(FAILED)
    expect(html).toContain('data-map="build-warnings"')
    // React escapes the quotes in the warning; the text is what matters.
    expect(html).toContain('path &quot;src/x.py&quot; matches no included file')
  })

  it('keeps the warnings visible on a built map, where the page still drew', () => {
    const html = render({
      ...ABSENT,
      built: true,
      reason: '',
      path: '/maps/proj-1a2b3c4d/index.html',
      bytes: 2048,
      build: { ok: true, error: '', warnings: ['node gates matched no file'] },
    })
    expect(html).toContain('data-map="frame"')
    expect(html).toContain('data-map="build-warnings"')
    expect(html).toContain('node gates matched no file')
  })

  // #379 pre-push review: the build's failure message used to be written into
  // the same slot as a transport error, and `load()` clears that slot as soon
  // as a request succeeds — so a 409 ("a build is already running") was erased
  // by the very poll that followed it. The message has its own slot now, and
  // the panel keeps rendering underneath it.
  it('reports a refused build without hiding the panel behind it', () => {
    const html = render(ABSENT, 0, {
      notice: '409 Conflict: a map build is already running for G:\\pydantic',
    })
    expect(html).toContain('data-map="notice"')
    expect(html).toContain('a map build is already running')
    // The action is still on screen underneath: a refusal is a sentence, not a
    // terminal state. (The full-screen `error` path lives in `Map`, not here,
    // so there is nothing in this render for it to collide with.)
    expect(html).toContain('data-map="build"')
  })

  it('shows no notice when the last build had nothing to say', () => {
    expect(render(ABSENT)).not.toContain('data-map="notice"')
  })
})
