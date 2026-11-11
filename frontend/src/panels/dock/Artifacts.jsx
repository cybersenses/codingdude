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
import { api, call } from '../../api'
import { Mermaid } from '../../ui.jsx'
import { WireframeView } from '../../WireframeView.jsx'
import { ARTIFACT_FOCUS_EVENT, takeArtifactFocusRequest } from '../../artifacts'

// R59 P0: moved verbatim out of App.jsx's DockPanel tab body. Live-pushed via
// SSE with a polling fallback; becomes the `artifacts` panel in P2.
export function Artifacts({ sessionId, initialItems = [] }) {
  const [items, setItems] = useState(initialItems)
  const [drafts, setDrafts] = useState({})
  // #242 seam: a failed poll or mutation must be visible, not "no artifacts yet".
  const [pollError, setPollError] = useState(null)
  const [mutError, setMutError] = useState(null)
  // R87-D: deep-link target — the chat card's View button fires
  // cd-focus-artifact; this panel scrolls to and rings that artifact.
  const [focusId, setFocusId] = useState(null)
  const itemRefs = useRef({})

  useEffect(() => {
    if (!sessionId) return
    let closed = false
    let fallback = null
    // R6: live push via SSE; fall back to the old 4s poll if the stream dies.
    const startPolling = () => {
      if (closed || fallback) return
      const poll = async () => {
        try {
          setItems(await call(`/sessions/${sessionId}/artifacts`))
          setPollError(null)
        } catch (e) {
          // Keep the last items; surface the failure (the #231 bug class).
          setPollError(e instanceof Error ? e.message : String(e))
        }
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

  useEffect(() => {
    const onFocus = (e) => {
      const id = e.detail && e.detail.id
      if (id) {
        // Consume the bus twin so a stale request can never fire a later mount.
        takeArtifactFocusRequest()
        setFocusId(id)
      }
    }
    window.addEventListener(ARTIFACT_FOCUS_EVENT, onFocus)
    return () => window.removeEventListener(ARTIFACT_FOCUS_EVENT, onFocus)
  }, [])
  // R87-D: a View click on a CLOSED panel dispatched before this listener
  // existed — the bus still holds the request; consume it at mount.
  useEffect(() => {
    const pending = takeArtifactFocusRequest()
    if (pending) setFocusId(pending)
  }, [])
  // SSR never runs effects, so the scroll is browser-only by construction
  // (same shape as WireframeView's focus scroll).
  useEffect(() => {
    if (!focusId) return
    const el = itemRefs.current[focusId]
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [focusId, items])

  async function respond(id, body) {
    try {
      await call(`/artifacts/${id}/respond`, { method: 'POST', body: JSON.stringify(body) })
      setItems(await call(`/sessions/${sessionId}/artifacts`))
      setMutError(null)
    } catch (e) {
      // A failed answer must not look successful (#242 class).
      setMutError(e instanceof Error ? e.message : String(e))
    }
  }

  // R58: retire a card whose run has ended — no answer, just off the list.
  async function dismiss(id) {
    try {
      await call(`/artifacts/${id}/dismiss`, { method: 'POST' })
      setItems(await call(`/sessions/${sessionId}/artifacts`))
      setMutError(null)
    } catch (e) {
      // A failed dismiss must leave the card in place (#242 class).
      setMutError(e instanceof Error ? e.message : String(e))
    }
  }

  if (!sessionId) return <div className="text-neutral-600">no session</div>
  return (
    <div className="space-y-2">
      {pollError && (
        <div data-poll-error="Artifacts" className="rounded border border-danger/50 bg-danger/10 p-2 text-[10px] text-danger">
          artifacts unavailable: {pollError}
        </div>
      )}
      {mutError && (
        <div data-poll-error="Artifacts" className="rounded border border-danger/50 bg-danger/10 p-2 text-[10px] text-danger">
          last action failed: {mutError}
        </div>
      )}
      {items.length === 0 && !pollError && <div className="text-neutral-600">no artifacts yet</div>}
      <p className="text-[10px] text-neutral-500">
        Artifacts are interactive things the agent hands you mid-run — choice cards to pick
        from, spec blocks you can edit, and HTML pages it renders for you right here.
      </p>
      {items.map((a) => (
        <div
          key={a.id}
          data-artifact={a.id}
          data-focused={focusId === a.id ? 'true' : undefined}
          ref={(el) => { itemRefs.current[a.id] = el }}
          className={focusId === a.id
            ? 'rounded border border-accent bg-neutral-900 p-2'
            : 'rounded border border-neutral-800 bg-neutral-900 p-2'}
        >
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
          ) : a.kind === 'wireframe' ? (
            <div className="space-y-1">
              <WireframeView payload={a.payload} theme="lofi" pack={{ title: a.title, id: a.id }} />
              {/* #320 (REQ-6 inline-edit half): the pack's DSL source is the
                  spec — edit it right here and save; the agent reads the edit
                  back via its feedback tool and re-emits the whole pack. Same
                  drafts + respond({content}) seam as the spec-block editor. */}
              {a.status === 'pending' && (
                <div>
                  <textarea
                    data-wireframe-edit={a.id}
                    className="h-28 w-full rounded bg-neutral-950 p-1 font-mono text-[10px] text-neutral-300"
                    title="the pack's DSL source is the spec — the agent reads your edit back and re-emits the whole pack"
                    value={drafts[a.id] ?? JSON.stringify(a.payload, null, 2)}
                    onChange={(e) => setDrafts((d) => ({ ...d, [a.id]: e.target.value }))}
                  />
                  <button
                    className="mt-1 rounded bg-accent px-2 py-0.5 text-[10px] text-accent-fg"
                    title="save the edited DSL — the agent treats it as the requirement for its next revision"
                    onClick={() => respond(a.id, { content: drafts[a.id] ?? JSON.stringify(a.payload, null, 2) })}
                  >save</button>
                </div>
              )}
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
