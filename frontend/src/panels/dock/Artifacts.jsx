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
import { api, call } from '../../api'
import { Mermaid } from '../../ui.jsx'

// R59 P0: moved verbatim out of App.jsx's DockPanel tab body. Live-pushed via
// SSE with a polling fallback; becomes the `artifacts` panel in P2.
export function Artifacts({ sessionId }) {
  const [items, setItems] = useState([])
  const [drafts, setDrafts] = useState({})

  useEffect(() => {
    if (!sessionId) return
    let closed = false
    let fallback = null
    // R6: live push via SSE; fall back to the old 4s poll if the stream dies.
    const startPolling = () => {
      if (closed || fallback) return
      const poll = async () => {
        try { setItems(await call(`/sessions/${sessionId}/artifacts`)) } catch { /* transient */ }
        if (!closed) fallback = setTimeout(poll, 4000)
      }
      poll()
    }
    const es = new EventSource(api.artifactStreamUrl(sessionId))
    es.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data)
        if (evt.event === 'snapshot') setItems(evt.artifacts)
        else if (evt.event === 'emitted') setItems((xs) => [evt.artifact, ...xs.filter((a) => a.id !== evt.artifact.id)])
        else if (evt.event === 'answered') setItems((xs) => xs.map((a) => (a.id === evt.artifact.id ? evt.artifact : a)))
      } catch { /* malformed frame: ignore */ }
    }
    es.onerror = () => { es.close(); startPolling() }
    return () => { closed = true; es.close(); if (fallback) clearTimeout(fallback) }
  }, [sessionId])

  async function respond(id, body) {
    try {
      await call(`/artifacts/${id}/respond`, { method: 'POST', body: JSON.stringify(body) })
      setItems(await call(`/sessions/${sessionId}/artifacts`))
    } catch { /* transient */ }
  }

  // R58: retire a card whose run has ended — no answer, just off the list.
  async function dismiss(id) {
    try {
      await call(`/artifacts/${id}/dismiss`, { method: 'POST' })
      setItems(await call(`/sessions/${sessionId}/artifacts`))
    } catch { /* transient */ }
  }

  if (!sessionId) return <div className="text-neutral-600">no session</div>
  if (items.length === 0) return <div className="text-neutral-600">no artifacts yet</div>
  return (
    <div className="space-y-2">
      <p className="text-[10px] text-neutral-500">
        Artifacts are interactive things the agent hands you mid-run — choice cards to pick
        from, spec blocks you can edit, and HTML pages it renders for you right here.
      </p>
      {items.map((a) => (
        <div key={a.id} className="rounded border border-neutral-800 bg-neutral-900 p-2">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[11px] font-semibold text-neutral-200">{a.title}</span>
            <span className="flex items-center gap-2 text-[9px] uppercase text-neutral-500">
              {a.kind} · {a.status}
              {a.status === 'pending' && (
                <button
                  className="rounded border border-neutral-700 px-1 py-0.5 text-[9px] normal-case text-neutral-400 hover:text-neutral-100"
                  title="retire this card — the run that asked is gone, nothing will read the answer"
                  onClick={() => dismiss(a.id)}
                >dismiss</button>
              )}
            </span>
          </div>
          {a.kind === 'html' ? (
            <iframe
              title={a.id}
              sandbox=""
              className="h-64 w-full rounded bg-white"
              srcDoc={a.payload.html}
            />
          ) : a.kind === 'qa' ? (
            <div className="space-y-1">
              {a.payload.questions.map((q, i) => (
                <div key={i} className="text-[10px] text-neutral-300">
                  {(() => {
                    const ans = a.response?.[String(i)] ?? a.response?.[i] ?? a.response
                    return (
                      <>
                        <span className="text-neutral-500">Q: </span>{q.question}
                        <span className="text-neutral-500"> · A: </span>
                        <span className="text-accent">{ans?.answer ?? JSON.stringify(ans)}</span>
                      </>
                    )
                  })()}
                </div>
              ))}
            </div>
          ) : a.kind === 'decision' ? (
            <pre className="whitespace-pre-wrap text-[10px] text-neutral-300">{a.payload.body || a.payload.title}</pre>
          ) : a.kind === 'choice' ? (
            <div className="flex flex-wrap gap-1">
              {a.payload.options.map((opt) => (
                <button
                  key={opt}
                  disabled={a.status !== 'pending'}
                  className={a.response?.pick === opt
                    ? 'rounded bg-accent px-2 py-0.5 text-[10px] text-accent-fg'
                    : 'rounded bg-neutral-800 px-2 py-0.5 text-[10px] text-neutral-300 hover:bg-neutral-700 disabled:opacity-40'}
                  onClick={() => respond(a.id, { pick: opt })}
                >{opt}</button>
              ))}
            </div>
          ) : a.status !== 'pending' ? (
            <pre className="whitespace-pre-wrap text-[10px] text-neutral-300">{a.response?.content ?? a.payload.markdown}</pre>
          ) : (
            <div>
              {a.payload.markdown.includes('```mermaid') && (
                <div className="mb-1">
                  {a.payload.markdown
                    .split(/```mermaid\n?/)
                    .slice(1)
                    .map((chunk, i) => (
                      <Mermaid key={i} code={chunk.split('```')[0]} />
                    ))}
                </div>
              )}
              <textarea
                className="h-28 w-full rounded bg-neutral-950 p-1 font-mono text-[10px] text-neutral-300"
                value={drafts[a.id] ?? a.payload.markdown}
                onChange={(e) => setDrafts((d) => ({ ...d, [a.id]: e.target.value }))}
              />
              <button
                className="mt-1 rounded bg-accent px-2 py-0.5 text-[10px] text-accent-fg"
                onClick={() => respond(a.id, { content: drafts[a.id] ?? a.payload.markdown })}
              >save</button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
