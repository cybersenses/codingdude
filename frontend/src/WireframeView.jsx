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
// R87 #330 (v3): region content is compiled to Wireloom source and rendered
// by wireloom itself (wireloom-adapter) — no more hand-rolled Sketch glyphs.
// The component stays a thin adapter: one async render effect + one state,
// keeping the #320 hook-order invariant trivial.
import React, { useEffect, useRef, useState } from 'react'
import { applyFocus, parseWireframe } from './wireframes'
import { WireframeFlowMap } from './wireframes/WireframeFlowMap.jsx'
import { implementPrompt, prefillComposer } from './composerPrefill'
import { renderPackScreens } from './wireloom-adapter'

export function WireframeView({ payload, theme = 'lofi', initialFocused = null, pack = null }) {
  const [focused, setFocused] = useState(initialFocused)
  // R87 #330: the compiled wireloom SVGs land here, keyed by screen id.
  const [rendered, setRendered] = useState({ svgById: {}, problems: [] })
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
  // R87 #330: compile + render every screen through wireloom. Keyed on
  // payload identity — vm derives deterministically from payload, so the
  // closure's vm always matches. The stale flag discards a late resolve from
  // a superseded payload (revision loop); pack id comes via ref because the
  // pack prop is an inline object (new identity every render).
  const packIdRef = useRef('wf')
  packIdRef.current = pack?.id ?? 'wf'
  useEffect(() => {
    if (!vm.ok) return
    let stale = false
    renderPackScreens(vm, 'dark', () => stale, packIdRef.current).then((out) => {
      if (!stale) setRendered(out)
    })
    return () => { stale = true }
  }, [payload, vm.ok])
  // #320: every hook call lives ABOVE this bail — a mounted instance whose
  // payload flips valid<->invalid must keep one stable hook order (#310 class).
  if (!vm.ok) {
    return <div className="text-[10px] text-danger">{vm.problems.join(' · ')}</div>
  }
  return (
    <div className="space-y-2">
      {(notes.length > 0 || vm.problems.length > 0 || rendered.problems.length > 0) && (
        <div className="text-[9px] text-neutral-500">
          renderer: {[...notes, ...vm.problems, ...rendered.problems].join(' · ')}
        </div>
      )}
      {vm.screens.map((s) => {
        const svg = rendered.svgById[s.id]
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
            {/* R87 #330 (v3): the wireloom SVG IS the layout. Framed screens
                get the fixed 16:10 canvas; the SVG letterboxes inside it.
                Stacked screens keep natural height. Until the async render
                resolves (SSR included) a pending placeholder holds the box. */}
            <div
              className={framed ? 'w-full' : 'w-full'}
              style={framed ? { aspectRatio: '16 / 10' } : undefined}
            >
              {svg
                ? (
                  <div
                    data-wireloom-svg={s.id}
                    className={framed
                      ? 'h-full max-h-full w-full [&>svg]:h-full [&>svg]:w-full'
                      : 'w-full [&>svg]:w-full'}
                    dangerouslySetInnerHTML={{ __html: svg }}
                  />
                )
                : (
                  <div
                    data-wireloom-pending={s.id}
                    className="flex min-h-[40px] h-full items-center justify-center text-[10px] text-neutral-600"
                  >
                    rendering…
                  </div>
                )}
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
