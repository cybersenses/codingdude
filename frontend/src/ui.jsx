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
import React, { useEffect, useRef, useState } from 'react'

// R59 P0: shared render primitives. Moved verbatim out of App.jsx — panels and
// chrome both need them, so they live below both.

// R6: render-only mermaid diagrams inside spec blocks. Renders each
// ```mermaid fence to SVG; on failure the raw fence stays visible.
export function Mermaid({ code }) {
  const ref = useRef(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const mermaid = (await import('mermaid')).default
        // SEC #251: agent-generated fences render here — the sandbox level is
        // pinned, not inherited from whatever the installed mermaid defaults to.
        mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' })
        const { svg } = await mermaid.render(`mmd-${Math.random().toString(36).slice(2)}`, code)
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e))
      }
    })()
    return () => { cancelled = true }
  }, [code])
  return error
    ? <div className="text-[9px] text-red-400">mermaid render failed: {error}</div>
    : <div ref={ref} className="mermaid-svg overflow-auto [&_svg]:max-w-full" />
}

// Injected at build time by vite.config.js — makes the running build visible
// so a stale bundle (or a server that hasn't restarted) is obvious on screen.
export const UI_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'dev'
export const UI_BUILD = typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : ''
export const UI_SHA = typeof __GIT_SHA__ !== 'undefined' ? __GIT_SHA__ : ''
export const shortStamp = (iso) => (iso ? iso.slice(5, 16).replace('T', ' ') : '')
