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
import { api } from '../../api'

// R59 P0: moved verbatim out of App.jsx's DockPanel tab body. Roadmap,
// tickets, PRDs, tech designs and decisions for the selected project; becomes
// the `planning` panel in P2.
export function Planning({ workdir }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [kind, setKind] = useState('ticket')

  async function refresh() {
    if (!workdir) return
    try {
      setData(await api.getPlanning(workdir))
      setErr('')
    } catch (e) { setErr(String(e.message)) }
  }
  useEffect(() => { refresh() }, [workdir])

  async function setStatus(fn, id, status) {
    await fn(workdir, id, status).catch(() => {})
    refresh()
  }
  async function add() {
    const title = newTitle.trim()
    if (!title) return
    const fn = kind === 'ticket' ? api.addTicket
      : kind === 'roadmap' ? api.addRoadmapItem
      : kind === 'prd' ? (wd) => api.addPrd(wd, title)
      : kind === 'design' ? (wd) => api.addDesign(wd, title)
      : api.addDecision
    try {
      await fn(workdir, title, '')
      setNewTitle('')
      setErr('')
    } catch (e) { setErr(String(e.message)) }
    refresh()
  }

  if (!workdir) {
    return <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">Select a project first.</div>
  }
  if (err && !data) {
    return (
      <div className="rounded border border-danger/50 bg-danger/10 p-3 text-xs text-danger">
        planning data unavailable: {err}{' '}
        <button className="ml-1 underline hover:opacity-80" onClick={refresh}>retry</button>
      </div>
    )
  }
  if (!data) {
    return <div className="text-ink-muted">loading…</div>
  }
  const statusColor = (s) => s === 'done' ? 'text-success'
    : s === 'in_progress' ? 'text-warning' : 'text-ink-muted'
  return (
      <div className="space-y-3">
      {err && (
        <div className="rounded border border-warning/50 bg-warning/10 px-2 py-1 text-[10px] text-warning">
          refresh failed: {err}
        </div>
      )}
      <div className="flex gap-1">
        <select
          className="rounded border border-neutral-700 bg-neutral-900 px-1 py-0.5 text-[10px] text-ink"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          aria-label="Planning item type"
        >
          <option value="ticket">ticket</option>
          <option value="roadmap">roadmap</option>
          <option value="decision">decision</option>
          <option value="prd">PRD</option>
          <option value="design">tech design</option>
        </select>
        <input
          className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-0.5 text-xs text-ink"
          placeholder="new title…"
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
        />
        <button className="rounded bg-brand-700 px-2 py-0.5 text-[10px] text-brand-fg" onClick={add}>add</button>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wide text-ink-muted">PRDs</div>
        {data.prds?.length === 0 && <div className="text-neutral-600">empty</div>}
        {data.prds?.map((p) => (
          <div key={p.id} className="flex items-center gap-1 rounded bg-neutral-900 p-1">
            <span
              className={`min-w-0 flex-1 truncate text-xs ${p.status === 'active' ? 'text-success' : p.status === 'draft' ? 'text-warning' : 'text-ink-muted'}`}
              title={p.body}
            >
              #{p.id} {p.title}
            </span>
            <select
              className="rounded border border-neutral-700 bg-neutral-900 px-1 text-[10px] text-ink"
              value={p.status}
              onChange={(e) => setStatus(api.setPrdStatus, p.id, e.target.value)}
              aria-label={`PRD status for ${p.title}`}
            >
              <option value="draft">draft</option>
              <option value="active">active</option>
              <option value="sunset">sunset</option>
            </select>
          </div>
        ))}
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wide text-ink-muted">Tech designs</div>
        {data.designs?.length === 0 && <div className="text-neutral-600">empty</div>}
        {data.designs?.map((d) => (
          <div key={d.id} className="flex items-center gap-1 rounded bg-neutral-900 p-1">
            <span
              className={`min-w-0 flex-1 truncate text-xs ${d.status === 'approved' ? 'text-success' : d.status === 'draft' ? 'text-warning' : 'text-ink-muted'}`}
              title={d.body}
            >
              #{d.id} {d.title}{d.prd_id && <span className="ml-1 text-[10px] text-neutral-500">PRD #{d.prd_id}</span>}
            </span>
            <select
              className="rounded border border-neutral-700 bg-neutral-900 px-1 text-[10px] text-ink"
              value={d.status}
              onChange={(e) => setStatus(api.setDesignStatus, d.id, e.target.value)}
              aria-label={`Design status for ${d.title}`}
            >
              <option value="draft">draft</option>
              <option value="approved">approved</option>
              <option value="superseded">superseded</option>
            </select>
          </div>
        ))}
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wide text-ink-muted">Roadmap</div>
        {data.roadmap.length === 0 && <div className="text-neutral-600">empty</div>}
        {data.roadmap.map((r) => (
          <div key={r.id} className="flex items-center gap-1 rounded bg-neutral-900 p-1">
            <span className={`min-w-0 flex-1 truncate text-xs ${statusColor(r.status)}`} title={r.body}>
              #{r.id} {r.title}
            </span>
            <select
              className="rounded border border-neutral-700 bg-neutral-900 px-1 text-[10px] text-ink"
              value={r.status}
              onChange={(e) => setStatus(api.setRoadmapStatus, r.id, e.target.value)}
              aria-label={`Roadmap status for ${r.title}`}
            >
              <option value="open">open</option>
              <option value="in_progress">in progress</option>
              <option value="done">done</option>
            </select>
          </div>
        ))}
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wide text-ink-muted">Tickets</div>
        {data.tickets.length === 0 && <div className="text-neutral-600">empty</div>}
        {data.tickets.map((t) => (
          <div key={t.id} className="flex items-center gap-1 rounded bg-neutral-900 p-1">
            <span className={`min-w-0 flex-1 truncate text-xs ${statusColor(t.status)}`} title={t.body}>
              #{t.id} {t.title}{t.commit_sha && <span className="ml-1 font-mono text-[10px] text-neutral-500">@{t.commit_sha}</span>}
            </span>
            <select
              className="rounded border border-neutral-700 bg-neutral-900 px-1 text-[10px] text-ink"
              value={t.status}
              onChange={(e) => setStatus(api.setTicketStatus, t.id, e.target.value)}
              aria-label={`Ticket status for ${t.title}`}
            >
              <option value="todo">todo</option>
              <option value="in_progress">in progress</option>
              <option value="done">done</option>
            </select>
          </div>
        ))}
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wide text-ink-muted">Design decisions</div>
        {data.decisions.length === 0 && <div className="text-neutral-600">empty</div>}
        {data.decisions.map((d) => (
          <div key={d.id} className="rounded bg-neutral-900 p-1" title={d.body}>
            <div className="truncate text-xs text-neutral-300">#{d.id} {d.title}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
