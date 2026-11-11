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
// R85 #316 (REQ-4): WireframeFlowMap — the SVG node-link overview of a
// wireframe pack. Layered layout comes from the pure seam (layoutScreens);
// this component renders it and owns the click-to-focus wiring. The parent
// (WireframeView) supplies focus state + onFocus and scrolls the focused
// screen's canvas box into view; standalone use falls back to internal state.
import React, { useState } from 'react'
import { applyFocus, FLOW_MAP_GRID, layoutScreens } from '../wireframes'

const NODE_W = 120
const NODE_H = 30
const PAD = 20

export function WireframeFlowMap({ screens, flows, focused, onFocus, initialFocused = null }) {
  // #320: `focused === undefined` means standalone (nothing owns focus); an
  // explicit null means the parent CLEARED focus. `focused ?? inner` conflated
  // the two, so a stale standalone id kept the map marked after the parent
  // cleared — the next map click then toggled the wrong way.
  const controlled = focused !== undefined
  const [inner, setInner] = useState(initialFocused)
  const cur = controlled ? focused : inner
  const set = (id) => {
    if (!controlled) setInner(applyFocus(cur, id))
    if (onFocus) onFocus(id)
  }
  const layout = layoutScreens(screens, flows)
  const rows = layout.layers.length
  const width = rows * FLOW_MAP_GRID.colW + PAD * 2
  const height = Math.max(...layout.layers.map((l) => l.length), 1) * FLOW_MAP_GRID.rowH + PAD * 2
  const node = (id) => layout.pos[id] ?? { x: 0, y: 0 }
  const hot = (id) => cur !== null && (id === cur)
  return (
    <svg
      className="w-full"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="flow map: screens and the workflows between them"
      style={{ maxHeight: 240 }}
    >
      <defs>
        <marker id="wfm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="fill-neutral-600" />
        </marker>
      </defs>
      {flows.map((f, i) => {
        const a = node(f.from)
        const b = node(f.to)
        const x1 = a.x + PAD + NODE_W
        const y1 = a.y + PAD + NODE_H / 2
        const x2 = b.x + PAD
        const y2 = b.y + PAD + NODE_H / 2
        const mx = (x1 + x2) / 2
        const live = cur !== null && (f.from === cur || f.to === cur)
        const d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`
        return (
          <g key={i} data-map-edge={`${f.from}:${f.to}`} data-focused={live ? 'true' : undefined}>
            <path
              d={d}
              className={live ? 'stroke-accent' : 'stroke-neutral-600'}
              fill="none"
              strokeWidth={live ? 1.6 : 1}
              markerEnd="url(#wfm-arrow)"
            />
            <path d={d} stroke="transparent" fill="none" strokeWidth={14} className="cursor-pointer" onClick={() => set(f.to)} />
            {(f.trigger || f.label) && (
              <text x={mx} y={(y1 + y2) / 2 - 3} textAnchor="middle" className="fill-neutral-500" style={{ fontSize: 8 }}>
                {f.trigger || f.label}
              </text>
            )}
          </g>
        )
      })}
      {layout.layers.flat().map((id) => {
        const s = screens.find((sc) => sc.id === id) ?? { title: '' }
        const p = node(id)
        const x = p.x + PAD
        const y = p.y + PAD
        return (
          <g
            key={id}
            data-map-node={id}
            data-focused={hot(id) ? 'true' : undefined}
            className="cursor-pointer"
            onClick={() => set(id)}
          >
            <rect
              x={x}
              y={y}
              width={NODE_W}
              height={NODE_H}
              rx={4}
              className={hot(id) ? 'fill-neutral-900 stroke-accent' : 'fill-neutral-900 stroke-neutral-700'}
            />
            <text x={x + 8} y={y + 19} className="fill-neutral-200" style={{ fontSize: 10 }}>
              {s.title || id}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
