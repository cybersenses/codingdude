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
import React from 'react'
import { impactMermaid } from '../../impact'
import { Mermaid } from '../../ui.jsx'

// R59 P0: presentational — the working-tree diff for the selected session.
// Split out of DockPanel's `tab === 'Diff'` branch so P1 can mount it as the
// `diff` panel and feed it from its own subscription instead of the dock's
// shared poll. Props are exactly the three fields that branch read.
export function DiffPanel({ diff, diffSummary, impact }) {
  const diffLines = (diff || '').split('\n')
  const added = diffLines.filter((l) => l.startsWith('+') && !l.startsWith('+++')).length
  const removed = diffLines.filter((l) => l.startsWith('-') && !l.startsWith('---')).length
  const lineClass = (l) => {
    if (l.startsWith('@@')) return 'text-accent'
    if (l.startsWith('diff --git') || l.startsWith('index ') || l.startsWith('+++') || l.startsWith('---'))
      return 'text-ink-muted'
    if (l.startsWith('+')) return 'text-success'
    if (l.startsWith('-')) return 'text-danger'
    return 'text-ink-muted'
  }
  if (!diff) {
    return (
      <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">
        No working-tree changes yet — edits the agent makes will appear here.
      </div>
    )
  }
  return (
    <div className="overflow-hidden rounded border border-line bg-surface">
      <div className="flex items-center gap-3 border-b border-line px-2 py-1 font-mono text-[10px]">
        <span className="text-success">+{added}</span>
        <span className="text-danger">-{removed}</span>
        <span className="ml-auto uppercase tracking-wide text-ink-muted">working tree</span>
      </div>
      {(diffSummary || []).length > 0 && (
        <div className="space-y-0.5 border-b border-line px-2 py-1.5">
          <div className="text-[9px] uppercase tracking-wide text-ink-muted">semantic changes</div>
          {diffSummary.filter((f) => f.summary).map((f) => (
            <div key={f.path} className="font-mono text-[10px]">
              <span className="text-brand-300">{f.path}</span>{' '}
              <span className="text-ink-muted">{f.summary}</span>
            </div>
          ))}
        </div>
      )}
      {impactMermaid(impact) && (
        <details className="border-b border-line px-2 py-1.5">
          <summary className="cursor-pointer text-[9px] uppercase tracking-wide text-ink-muted">impact graph</summary>
          <div className="pt-1">
            <Mermaid code={impactMermaid(impact)} />
          </div>
        </details>
      )}
      <div className="max-h-[70vh] overflow-auto p-2 font-mono text-[11px] leading-[1.5]">
        {diffLines.map((l, i) => (
          <div key={i} className={`whitespace-pre ${lineClass(l)}`}>{l || ' '}</div>
        ))}
      </div>
    </div>
  )
}
