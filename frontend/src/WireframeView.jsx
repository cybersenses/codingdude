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
// R85 #314: lo-fi wireframe renderer (Q2c: neutral grayscale). All parsing
// lives in the pure seam wireframes.ts — this component only renders its
// view model, so a malformed pack degrades to a warning line, never a crash.
import React, { useEffect, useRef, useState } from 'react'
import { applyFocus, parseWireframe, screenTracks } from './wireframes'
import { WireframeFlowMap } from './wireframes/WireframeFlowMap.jsx'
import { implementPrompt, prefillComposer } from './composerPrefill'

// R87-B: lo-fi sketch glyphs per widget kind — the drawing a wireframe owes
// the user (v1 rendered the widget vocab as text tags, which read as mush).
// One viewBox, stroke-neutral, scaled to the region; unknown kinds draw
// nothing (a bare labeled box is the honest generic).
const GLYPH_WIDGETS = new Set([
  'nav', 'header', 'form', 'table', 'list', 'text', 'chart', 'actions', 'tabs', 'image', 'code', 'placeholder',
])

function Sketch({ kind }) {
  const bars = (xs, y, h) => xs.map((x, i) => (
    <rect key={i} x={x[0]} y={y + i * (h + 5)} width={x[1]} height={h} fill="currentColor" stroke="none" />
  ))
  let shapes = null
  switch (kind) {
    case 'nav':
      shapes = bars([[8, 30], [8, 48], [8, 38]], 6, 4)
      break
    case 'list':
      shapes = bars([[4, 92], [4, 84], [4, 90], [4, 70]], 5, 3)
      break
    case 'text':
      shapes = bars([[4, 92], [4, 92], [4, 56]], 8, 3)
      break
    case 'code':
      shapes = bars([[4, 76], [14, 58], [14, 72], [4, 46]], 6, 3)
      break
    case 'chart':
      shapes = (
        <>
          <polyline points="4,44 25,20 45,34 65,12 96,26" />
          <line x1="4" y1="52" x2="96" y2="52" />
        </>
      )
      break
    case 'form':
      shapes = (
        <>
          <rect x="4" y="6" width="60" height="10" rx="1" />
          <rect x="4" y="22" width="60" height="10" rx="1" />
          <rect x="64" y="40" width="28" height="10" rx="2" />
        </>
      )
      break
    case 'image':
      shapes = (
        <>
          <rect x="4" y="4" width="92" height="52" />
          <line x1="4" y1="4" x2="96" y2="56" />
          <line x1="96" y1="4" x2="4" y2="56" />
        </>
      )
      break
    case 'table':
      shapes = (
        <>
          <rect x="4" y="4" width="92" height="52" />
          <line x1="35" y1="4" x2="35" y2="56" />
          <line x1="66" y1="4" x2="66" y2="56" />
          <line x1="4" y1="21" x2="96" y2="21" />
          <line x1="4" y1="38" x2="96" y2="38" />
        </>
      )
      break
    case 'actions':
      shapes = (
        <>
          <rect x="50" y="22" width="42" height="10" rx="5" />
          <rect x="30" y="38" width="30" height="9" rx="4.5" />
        </>
      )
      break
    case 'tabs':
      shapes = (
        <>
          <rect x="2" y="4" width="28" height="9" rx="4" />
          <rect x="34" y="4" width="28" height="9" rx="4" />
          <rect x="66" y="4" width="28" height="9" rx="4" />
          <line x1="2" y1="18" x2="98" y2="18" />
        </>
      )
      break
    case 'header':
      shapes = (
        <>
          <rect x="2" y="4" width="96" height="12" rx="1" />
          <circle cx="10" cy="10" r="4" />
          <line x1="70" y1="10" x2="92" y2="10" />
        </>
      )
      break
    case 'placeholder':
      shapes = (
        <>
          <line x1="4" y1="56" x2="36" y2="4" />
          <line x1="28" y1="56" x2="60" y2="4" />
          <line x1="52" y1="56" x2="84" y2="4" />
          <line x1="76" y1="56" x2="96" y2="22" />
        </>
      )
      break
    default:
      shapes = null
  }
  return (
    <svg
      data-glyph={kind}
      viewBox="0 0 100 60"
      preserveAspectRatio="none"
      className="h-full max-h-full w-full text-neutral-600"
      stroke="currentColor"
      strokeWidth="1.5"
      fill="none"
      aria-hidden="true"
    >
      {shapes}
    </svg>
  )
}

export function WireframeView({ payload, theme = 'lofi', initialFocused = null, pack = null }) {
  const [focused, setFocused] = useState(initialFocused)
  // A re-emitted pack (revision loop) invalidates focus — screen ids may differ.
  // Intentionally keyed on payload identity only (no react-hooks plugin here).
  useEffect(() => { setFocused(initialFocused) }, [payload])
  const vm = parseWireframe(payload)
  // Q11a: the theme prop is reserved from day one; only 'lofi' (Q2c) is wired.
  const notes = !theme || theme === 'lofi' ? [] : [`unknown theme "${theme}" — rendering lofi`]
  // REQ-4 click-to-focus: focusing (from the map or a screen title) scrolls
  // that screen's canvas box into view. SSR never runs effects, so this is
  // browser-only by construction.
  const boxRefs = useRef({})
  useEffect(() => {
    if (!vm.ok) return
    const el = focused ? boxRefs.current[focused] : null
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [focused, vm.ok])
  const setFocus = (id) => setFocused((f) => applyFocus(f, id))
  // R87-A/B: resolve track sizes up front so track problems land in the
  // renderer line (which renders above the screens), and the JSX map just
  // looks sizes up. Plain data work — no hooks, so the #320 ordering guard
  // is unaffected.
  const trackNotes = []
  const tracksById = new Map()
  if (vm.ok) {
    for (const s of vm.screens) tracksById.set(s.id, screenTracks(s, trackNotes))
  }
  // #320: every hook call lives ABOVE this bail — a mounted instance whose
  // payload flips valid<->invalid must keep one stable hook order (#310 class).
  if (!vm.ok) {
    return <div className="text-[10px] text-danger">{vm.problems.join(' · ')}</div>
  }
  return (
    <div className="space-y-2">
      {(notes.length > 0 || vm.problems.length > 0 || trackNotes.length > 0) && (
        <div className="text-[9px] text-neutral-500">
          renderer: {[...notes, ...vm.problems, ...trackNotes].join(' · ')}
        </div>
      )}
      {vm.screens.map((s) => {
        const tracks = tracksById.get(s.id)
        const framed = s.template !== ''
        return (
          <div
            key={s.id}
            data-screen={s.id}
            data-focused={focused === s.id ? 'true' : undefined}
            ref={(el) => { boxRefs.current[s.id] = el }}
            className={focused === s.id
              ? 'rounded border border-accent bg-neutral-950 p-2'
              : 'rounded border border-neutral-800 bg-neutral-950 p-2'}
          >
            <div className="mb-1 flex items-center gap-1">
              <button
                data-screen-title={s.title || s.id}
                className="block text-left text-[10px] font-semibold text-neutral-300 hover:text-neutral-100"
                aria-pressed={focused === s.id}
                title="click to focus this screen"
                onClick={() => setFocus(s.id)}
              >{s.title || s.id}</button>
              {/* REQ-7 / Q6b+Q12b: per-screen implement handoff — prefills the
                  composer; sending stays the user's act. */}
              <button
                type="button"
                data-implement={s.id}
                className="rounded border border-neutral-700 px-1 py-0.5 text-[9px] normal-case text-neutral-400 hover:text-neutral-100"
                title="prefill the composer with an implement prompt for this screen"
                onClick={() => prefillComposer(implementPrompt(s.title || s.id, pack?.title ?? '', pack?.id ?? ''))}
              >implement</button>
            </div>
            {/* R87-B: fixed 16:10 frame — a screen canvas, not a spreadsheet.
                Stacked regions (no template) keep natural height. */}
            <div
              className="grid gap-1"
              style={framed
                ? {
                  gridTemplateAreas: s.template,
                  gridTemplateColumns: tracks.columns,
                  gridTemplateRows: tracks.rows,
                  aspectRatio: '16 / 10',
                }
                : undefined}
            >
              {s.regions.map((r, i) => (
                <div
                  key={r.name || i}
                  title={r.notes || undefined}
                  className="flex min-h-0 flex-col overflow-hidden rounded-[3px] border border-dashed border-neutral-700 bg-neutral-900 p-1"
                  style={r.name && s.template ? { gridArea: r.name } : undefined}
                >
                  <div className="flex items-baseline justify-between gap-1">
                    <span className="truncate text-[10px] leading-none text-neutral-200">{r.label || r.name || '·'}</span>
                  </div>
                  {GLYPH_WIDGETS.has(r.widget)
                    ? (
                      <div className="mt-0.5 min-h-0 flex-1">
                        <Sketch kind={r.widget} />
                      </div>
                    )
                    : <div data-glyph="generic" className="min-h-0 flex-1" />}
                </div>
              ))}
            </div>
          </div>
        )
      })}
      {/* R87-B: map after the canvases — overview follows detail. */}
      {vm.flows.length > 0 && (
        <div className="rounded border border-neutral-800 bg-neutral-950 p-2">
          <div className="mb-1 text-[10px] font-semibold text-neutral-300">flow map</div>
          <WireframeFlowMap screens={vm.screens} flows={vm.flows} focused={focused} onFocus={setFocus} />
        </div>
      )}
    </div>
  )
}
