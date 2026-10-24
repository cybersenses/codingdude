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
import { call } from '../api'
import { buildAnswers } from '../askUser'

// R59 P0: moved verbatim out of App.jsx. These six render inside the chat
// transcript and share one lifecycle (they appear mid-run and settle with the
// run), so they live together — the same grouping CodeEditor.jsx already uses
// for CodeEditor + CodeDiff.

export function ToolTimeline({ events }) {
  const [open, setOpen] = useState(false)
  if (!events.length) return null
  return (
    <div className="my-1 overflow-hidden rounded border border-line bg-surface/60 text-xs">
      <button
        className="flex w-full items-center gap-2 px-2 py-1 text-left text-ink-muted hover:text-ink"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span aria-hidden="true">{open ? '\u25be' : '\u25b8'}</span>
        <span>{events.length} tool call{events.length > 1 ? 's' : ''}</span>
        <span className="ml-auto font-mono text-[10px] text-ink-muted/70">
          {events.length ? (events[events.length - 1].tool_name || '') : ''}
        </span>
      </button>
      {open && (
        <div className="space-y-1 border-t border-line px-2 py-2">
          {events.map((e, i) => (
            <div key={i} className="rounded bg-canvas p-1.5 font-mono text-[11px]">
              <div className="text-accent">{e.tool_name || e.type}</div>
              {e.result != null && (
                <pre className="whitespace-pre-wrap text-ink-muted">
                  {typeof e.result === 'string' ? e.result : JSON.stringify(e.result, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function EditBlock({ edit, sessionId, onRevert }) {
  const [state, setState] = useState('applied') // applied | reverted
  const removed = edit.before ? edit.before.split('\n') : []
  const added = edit.after ? edit.after.split('\n') : []
  const beforeSet = new Set(removed)
  const afterSet = new Set(added)
  const removedLines = removed.filter((l) => !afterSet.has(l))
  const addedLines = added.filter((l) => !beforeSet.has(l))
  return (
    <div className="my-1 rounded border border-accent/50 bg-accent/10 p-2 text-xs">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-mono text-[10px] text-accent">{edit.path}</span>
        {state === 'applied' ? (
          <button
            className="rounded bg-danger px-2 py-0.5 text-[10px] text-danger-fg"
            onClick={() => {
              call(`/sessions/${sessionId}/file`, {
                method: 'PUT',
                body: JSON.stringify({ path: edit.path, content: edit.before }),
              })
                .then(() => { setState('reverted'); onRevert(edit) })
                .catch(() => {})
            }}
          >Revert</button>
        ) : (
          <span className="text-[10px] text-ink-muted">reverted</span>
        )}
      </div>
      <pre className="whitespace-pre-wrap font-mono text-[10px] leading-tight">
        {removedLines.map((l, i) => <div key={'r' + i} className="text-danger">- {l}</div>)}
        {addedLines.map((l, i) => <div key={'a' + i} className="text-success">+ {l}</div>)}
      </pre>
    </div>
  )
}

export function AskUserCard({ ask, runId }) {
  const [picks, setPicks] = useState({})
  const [texts, setTexts] = useState({})
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  if (!ask || !ask.questions || !ask.questions.length) return null
  if (sent) return null
  const submit = () => {
    if (sending) return
    setSending(true)
    setError('')
    const out = buildAnswers(ask.questions || [], picks, texts)
    call(`/runs/${runId}/ask`, { method: 'POST', body: JSON.stringify({ answers: out }) })
      .then(() => setSent(true))
      .catch((e) => { setError(String(e)); setSending(false) })
  }
  return (
    <div className="my-2 overflow-hidden rounded-lg border border-accent/50 bg-surface">
      <div className="border-b border-line bg-accent/10 px-3 py-2 text-xs font-semibold text-accent">
        Questions for you
      </div>
      <div className="space-y-3 px-3 py-2">
        {(ask.questions || []).map((q) => {
          const hasOptions = (q.options || []).length > 0
          const setPick = (fn) => setPicks((a) => ({ ...a, [q.question]: fn(a[q.question]) }))
          const setText = (v) => setTexts((a) => ({ ...a, [q.question]: v }))
          return (
          <div key={q.question}>
            <div className="mb-1 text-xs text-ink">{q.question}</div>
            {hasOptions ? (
              <div className="space-y-1">
                {(q.options || []).map((o) => (
                  <label key={o} className="flex items-center gap-2 text-xs text-ink-muted">
                    <input
                      type={q.multi ? 'checkbox' : 'radio'}
                      name={q.question}
                      checked={q.multi
                        ? (picks[q.question] || []).includes(o)
                        : picks[q.question] === o}
                      onChange={() => setPick((cur) => {
                        if (q.multi) {
                          const list = Array.isArray(cur) ? cur : []
                          return list.includes(o) ? list.filter((x) => x !== o) : [...list, o]
                        }
                        return o
                      })}
                    />
                    {o}
                  </label>
                ))}
                <label className="flex items-center gap-2 text-xs text-ink-muted">
                  Other…
                  <input
                    className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
                    placeholder="type your own answer"
                    value={texts[q.question] || ''}
                    onChange={(e) => setText(e.target.value)}
                  />
                </label>
              </div>
            ) : (
              <input
                className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
                value={texts[q.question] || ''}
                onChange={(e) => setText(e.target.value)}
              />
            )}
          </div>
          )
        })}
      </div>
      {error && <div className="px-3 py-1 text-xs text-danger">{error}</div>}
      <div className="flex justify-end border-t border-line px-3 py-2">
        <button
          className="rounded bg-brand px-3 py-1.5 text-xs font-medium text-brand-fg hover:bg-brand-hover"
          onClick={submit}
          disabled={sending}
        >{sending ? 'Sending…' : 'Send answers'}</button>
      </div>
    </div>
  )
}

export function PendingArtifactCard({ items, onResponded }) {
  // #189: choice cards / spec blocks surface here in the chat so the user
  // actually sees them mid-run (the Artifacts tab alone hid them).
  // Every pending card is answerable — one shared header, one body each.
  const [drafts, setDrafts] = useState({})
  const [errs, setErrs] = useState({})
  if (!items.length) return null
  const respond = (item, body) => {
    call(`/artifacts/${item.id}/respond`, { method: 'POST', body: JSON.stringify(body) })
      .then(onResponded)
      .catch((e) => setErrs((m) => ({ ...m, [item.id]: String(e) })))
  }
  // R58: no run is alive to read an answer, so let the user just clear it.
  const dismiss = (item) => {
    call(`/artifacts/${item.id}/dismiss`, { method: 'POST' })
      .then(onResponded)
      .catch((e) => setErrs((m) => ({ ...m, [item.id]: String(e) })))
  }
  return (
    <div className="my-2 overflow-hidden rounded-lg border border-brand-400/50 bg-surface">
      <div className="border-b border-line bg-brand-400/10 px-3 py-2 text-xs font-semibold text-brand-300">
        The agent is waiting on you — {items.length} pending card{items.length > 1 ? 's' : ''}
      </div>
      {items.map((item) => (
        <div key={item.id} className="space-y-2 border-b border-line px-3 py-2 last:border-b-0">
          <div className="flex items-center gap-2 text-xs text-ink">
            {item.title}
            <span className="font-mono text-[9px] font-normal uppercase text-ink-muted">{item.kind}</span>
            <button
              className="ml-auto rounded border border-line px-1.5 py-0.5 text-[9px] text-ink-muted hover:text-ink"
              title="retire this card — the run that asked is gone, nothing will read the answer"
              onClick={() => dismiss(item)}
            >dismiss</button>
          </div>
          {item.kind === 'choice' ? (
            <div className="flex flex-wrap gap-1">
              {(item.payload.options || []).map((opt) => (
                <button
                  key={opt}
                  className="rounded bg-neutral-800 px-2 py-0.5 text-[10px] text-neutral-200 hover:bg-brand-700 hover:text-brand-fg"
                  onClick={() => respond(item, { pick: opt })}
                >{opt}</button>
              ))}
            </div>
          ) : (
            <div>
              <textarea
                className="h-24 w-full rounded bg-neutral-950 p-1 font-mono text-[10px] text-neutral-300"
                value={drafts[item.id] ?? ''}
                placeholder={(item.payload.markdown || '')}
                onChange={(e) => setDrafts((d) => ({ ...d, [item.id]: e.target.value }))}
              />
              <button
                className="mt-1 rounded bg-brand px-2 py-0.5 text-[10px] text-brand-fg"
                onClick={() => respond(item, { content: drafts[item.id] || item.payload.markdown || '' })}
              >save</button>
            </div>
          )}
          {errs[item.id] && <div className="text-[10px] text-danger">{errs[item.id]}</div>}
        </div>
      ))}
    </div>
  )
}

export function ApprovalCard({ command, onDecide }) {
  return (
    <div className="my-2 overflow-hidden rounded-lg border border-warning/50 bg-surface">
      <div className="flex items-center gap-2 border-b border-line bg-warning/10 px-3 py-2">
        <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-warning"></span>
        <span className="text-xs font-semibold text-warning">Approval needed</span>
        <span className="ml-auto text-[11px] text-ink-muted">nothing runs until you decide</span>
      </div>
      <pre className="overflow-x-auto border-b border-line bg-canvas px-3 py-2 font-mono text-xs text-ink">{command}</pre>
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          className="rounded bg-brand px-3 py-1.5 text-xs font-medium text-brand-fg hover:bg-brand-hover"
          onClick={() => onDecide('approve')}
        >Approve once</button>
        <button
          className="rounded border border-line px-3 py-1.5 text-xs text-ink-muted hover:text-ink"
          onClick={() => onDecide('pattern')}
        >Approve all matching</button>
        <button
          className="ml-auto rounded border border-danger/50 px-3 py-1.5 text-xs text-danger hover:bg-danger/10"
          onClick={() => onDecide('deny')}
        >Deny</button>
      </div>
    </div>
  )
}

export function PlanCard({ sessionId, onDecide }) {
  const [plan, setPlan] = useState(null)
  useEffect(() => {
    if (!sessionId) return
    let stop = false
    async function poll() {
      try {
        const p = await call(`/sessions/${sessionId}/plan`)
        if (!stop) setPlan(p && p.goal ? p : null)
      } catch { /* transient */ }
      if (!stop) setTimeout(poll, 3000)
    }
    poll()
    return () => { stop = true }
  }, [sessionId])
  if (!plan) return null
  const statusColor = plan.status === 'rejected' ? 'text-danger'
    : plan.status === 'done' ? 'text-brand-400' : 'text-warning'
  return (
    <div className="my-2 rounded border border-accent/50 bg-accent/15 p-3">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-semibold text-accent">Plan — {plan.goal}</span>
        <span className={`text-xs ${statusColor}`}>{plan.status}</span>
      </div>
      <ol className="space-y-0.5">
        {plan.steps.map((s, i) => (
          <li key={i} className="text-xs text-neutral-300">
            {s.status === 'done' ? '☑' : '☐'} {s.text}
          </li>
        ))}
      </ol>
      {plan.status === 'approved' && onDecide && (
        <div className="mt-2 flex gap-2">
          <button className="rounded bg-brand-700 px-3 py-1 text-xs text-brand-fg hover:bg-brand-600"
            onClick={() => onDecide('approve')}>Approve plan</button>
          <button className="rounded bg-danger px-3 py-1 text-xs text-danger-fg hover:bg-danger/90"
            onClick={() => onDecide('deny')}>Reject</button>
        </div>
      )}
    </div>
  )
}
