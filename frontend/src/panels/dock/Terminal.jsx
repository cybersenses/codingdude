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
import React, { useState } from 'react'
import { call } from '../../api'

// R59 P0: moved verbatim out of App.jsx's DockPanel tab body. Session shell
// access; becomes the `terminal` panel in P2.
export function Terminal({ sessionId }) {
  const [cmd, setCmd] = useState('')
  const [output, setOutput] = useState([])
  const [busy, setBusy] = useState(false)
  const run = async () => {
    if (!cmd.trim() || busy) return
    setBusy(true)
    try {
      const r = await call(`/sessions/${sessionId}/exec`, {
        method: 'POST',
        body: JSON.stringify({ command: cmd.trim() }),
      })
      setOutput((o) => [...o, { cmd: cmd.trim(), exit: r.exit, out: r.output }])
    } catch { /* transient */ }
    setBusy(false)
    setCmd('')
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="min-h-0 flex-1 overflow-auto rounded bg-canvas p-2 font-mono text-[11px]">
        {output.length === 0 && <div className="text-ink-muted">no commands yet</div>}
        {output.map((o, i) => (
          <div key={i} className="mb-2">
            <div className="text-accent">$ {o.cmd}</div>
            <pre className="whitespace-pre-wrap text-ink-muted">{o.out || '(no output)'}</pre>
            <div className={o.exit === 0 ? 'text-success' : 'text-danger'}>exit {o.exit}</div>
          </div>
        ))}
      </div>
      <div className="flex gap-1">
        <input
          className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 font-mono text-xs text-ink"
          value={cmd}
          onChange={(e) => setCmd(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); run() } }}
          placeholder="shell command…"
        />
        <button
          className="rounded bg-brand px-2 py-1 text-xs text-brand-fg"
          onClick={run}
          disabled={busy}
        >run</button>
      </div>
    </div>
  )
}
