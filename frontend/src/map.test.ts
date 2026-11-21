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
}

function render(state, nonce = 0) {
  return renderToString(
    createElement(MapView, { sessionId: 's-1', state, nonce, onRefresh: () => {} }),
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
})
