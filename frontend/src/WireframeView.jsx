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
import React from 'react'
import { parseWireframe } from './wireframes'

const WIDGETS = new Set(['nav', 'header', 'form', 'table', 'list', 'text', 'chart', 'actions', 'tabs', 'image', 'code', 'placeholder'])

export function WireframeView({ payload, theme = 'lofi' }) {
  const vm = parseWireframe(payload)
  if (!vm.ok) {
    return <div className="text-[10px] text-danger">{vm.problems.join(' · ')}</div>
  }
  // Q11a: the theme prop is reserved from day one; only 'lofi' (Q2c) is wired.
  const notes = !theme || theme === 'lofi' ? [] : [`unknown theme "${theme}" — rendering lofi`]
  return (
    <div className="space-y-2">
      {notes.length > 0 && (
        <div className="text-[9px] text-neutral-500">renderer: {notes.join(' · ')}</div>
      )}
      {vm.problems.length > 0 && (
        <div className="text-[9px] text-neutral-500">renderer: {vm.problems.join(' · ')}</div>
      )}
      {vm.screens.map((s) => (
        <div key={s.id} className="rounded border border-neutral-800 bg-neutral-950 p-2">
          <div className="mb-1 text-[10px] font-semibold text-neutral-300">{s.title || s.id}</div>
          <div
            className="grid gap-1"
            style={s.template ? { gridTemplateAreas: s.template } : undefined}
          >
            {s.regions.map((r, i) => (
              <div
                key={r.name || i}
                className="min-h-8 rounded border border-dashed border-neutral-700 bg-neutral-900 p-1"
                style={r.name && s.template ? { gridArea: r.name } : undefined}
              >
                <div className="flex items-baseline justify-between gap-1">
                  <span className="text-[10px] text-neutral-200">{r.label || r.name || '·'}</span>
                  <span className="text-[8px] uppercase text-neutral-500">
                    {WIDGETS.has(r.widget) ? r.widget : r.widget ? `?${r.widget}` : ''}
                  </span>
                </div>
                {r.notes && <div className="mt-0.5 text-[9px] text-neutral-500">{r.notes}</div>}
              </div>
            ))}
          </div>
        </div>
      ))}
      {vm.flows.length > 0 && (
        <div className="rounded border border-neutral-800 bg-neutral-950 p-2">
          <div className="mb-1 text-[10px] font-semibold text-neutral-300">flows</div>
          {vm.flows.map((f, i) => (
            <div key={i} className="text-[10px] text-neutral-400">
              <span className="text-neutral-200">{f.from}</span>
              <span className="text-neutral-500"> → </span>
              <span className="text-neutral-200">{f.to}</span>
              {f.trigger && <span className="text-neutral-500"> · {f.trigger}</span>}
              {f.label && <span className="text-neutral-500"> — {f.label}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
