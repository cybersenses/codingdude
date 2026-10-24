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
import React, { useEffect, useState } from 'react'
import { call } from '../../api'

// R59 P0: moved verbatim out of App.jsx's DockPanel tab body. Session notes +
// project guidance; becomes the `notes` panel in P2.
export function Notes({ sessionId, workdir }) {
  const [notes, setNotes] = useState([])
  const [keep, setKeep] = useState(null)
  const [draft, setDraft] = useState('')
  const [offset, setOffset] = useState('')
  const [pnotes, setPnotes] = useState([])
  const [pdraft, setPdraft] = useState('')

  useEffect(() => {
    if (!sessionId) return
    let live = true
    const load = async () => {
      try {
        const [n, sessions] = await Promise.all([
          call(`/sessions/${sessionId}/notes`),
          call(`/sessions?workdir=${encodeURIComponent(workdir || '')}`),
        ])
        if (!live) return
        setNotes(n)
        setKeep((sessions.find((x) => x.session_id === sessionId) || {}).keep_for_evals ?? false)
      } catch { /* transient */ }
    }
    load()
    return () => { live = false }
  }, [sessionId])

  const loadProjectNotes = async () => {
    if (!workdir) return
    try { setPnotes(await call(`/notes?workdir=${encodeURIComponent(workdir)}`)) } catch { /* transient */ }
  }
  useEffect(() => { loadProjectNotes() }, [workdir])

  if (!sessionId) return <div className="text-neutral-600">no session</div>
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-1.5 text-xs text-neutral-300">
        <input
          type="checkbox"
          checked={!!keep}
          onChange={async (e) => {
            setKeep(e.target.checked)
            try { await call(`/sessions/${sessionId}/keep`, { method: 'POST', body: JSON.stringify({ keep: e.target.checked }) }) } catch { /* transient */ }
          }}
        />
        keep for evals
      </label>
      <div className="flex gap-1">
        <input
          className="w-full rounded bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
          placeholder="note at this point in the session…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <input
          className="w-16 rounded bg-neutral-900 px-2 py-1 text-xs text-neutral-400"
          placeholder="s"
          value={offset}
          onChange={(e) => setOffset(e.target.value)}
        />
        <button
          className="rounded bg-brand px-2 py-1 text-xs text-brand-fg"
          onClick={async () => {
            if (!draft.trim()) return
            const body = { content: draft.trim() }
            const off = parseFloat(offset)
            if (!Number.isNaN(off)) { body.offset_s = off }
            try {
              await call(`/sessions/${sessionId}/notes`, { method: 'POST', body: JSON.stringify(body) })
              setDraft(''); setOffset('')
              setNotes(await call(`/sessions/${sessionId}/notes`))
            } catch { /* transient */ }
          }}
        >add</button>
      </div>
      {notes.length === 0 && <div className="text-neutral-600">no notes yet</div>}
      {notes.map((n) => (
        <div key={n.id} className="rounded bg-neutral-900 p-1.5">
          <div className="text-xs text-neutral-200">{n.content}</div>
          <div className="text-[9px] text-neutral-500">
            {n.offset_s != null ? `${n.offset_s}s · ` : ''}{(n.created_at || '').slice(11, 19)}
          </div>
        </div>
      ))}

      <div className="mt-3 border-t border-neutral-800 pt-2">
        <div className="mb-1 text-[10px] font-semibold uppercase text-neutral-400">project notes</div>
        <div className="text-[9px] text-neutral-500">guidance for every session in this project — the agent reads these</div>
        <div className="mt-1 flex gap-1">
          <input
            className="w-full rounded bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            placeholder="standing guidance for this project…"
            value={pdraft}
            onChange={(e) => setPdraft(e.target.value)}
          />
          <button
            className="rounded bg-brand px-2 py-1 text-xs text-brand-fg"
            onClick={async () => {
              if (!pdraft.trim() || !workdir) return
              try {
                await call('/notes', { method: 'POST', body: JSON.stringify({ workdir, content: pdraft.trim() }) })
                setPdraft('')
                loadProjectNotes()
              } catch { /* transient */ }
            }}
          >add</button>
        </div>
        {pnotes.length === 0 && <div className="text-neutral-600">no project notes</div>}
        {pnotes.map((n) => (
          <div key={n.id} className="mt-1 flex items-start justify-between gap-1 rounded bg-neutral-900 p-1.5">
            <div>
              <div className="text-xs text-neutral-200">{n.content}</div>
              <div className="text-[9px] text-neutral-500">{(n.created_at || '').slice(11, 19)}</div>
            </div>
            <div className="flex shrink-0 gap-1">
              <button
                title="mark dealt with"
                className="rounded bg-neutral-800 px-1.5 text-[10px] text-neutral-300 hover:bg-neutral-700"
                onClick={async () => { try { await call(`/notes/${n.id}/resolve`, { method: 'POST' }); loadProjectNotes() } catch { /* transient */ } }}
              >✓</button>
              <button
                title="delete"
                className="rounded bg-neutral-800 px-1.5 text-[10px] text-neutral-300 hover:bg-neutral-700"
                onClick={async () => { try { await call(`/notes/${n.id}`, { method: 'DELETE' }); loadProjectNotes() } catch { /* transient */ } }}
              >✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
