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
import React, { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import CodeEditor, { CodeDiff } from './CodeEditor.jsx'
import { closeTab, openTab } from './editor'
import { api, authLocal, call, checkAuth, login } from './api'
import { SSE_MAX_RETRIES, runToReattach, sseRetryDelayMs } from './reattach'
import { activeProcesses, describeProcess, mergeProcesses } from './processes'
import { PANE_SPECS, paneWidth } from './panes'
import { ACTIONS, buildActionPrompt } from './aiActions'
import { groupEventsByRun, pickRunId } from './runs'
import { pickPending } from './pending'
import { buildAnswers, clearPendingPrompts } from './askUser'
import { pendingArtifacts } from './artifacts'
import { buildSpans } from './waterfall'
import { buildTour } from './tour'
import { buildDesignDocPrompt } from './designdoc'
import { impactMermaid } from './impact'
import { callgraphMermaid, graphView } from './callgraph'
import { cfgMermaid } from './cfgView'
import { buildRepoQuestionPrompt } from './repoqa'
import { checklistPrompt } from './checklists'
import { structureRows } from './structure'
import logoUrl from './assets/logo.png'

// R6: render-only mermaid diagrams inside spec blocks. Renders each
// ```mermaid fence to SVG; on failure the raw fence stays visible.
function Mermaid({ code }) {
  const ref = useRef(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const mermaid = (await import('mermaid')).default
        mermaid.initialize({ startOnLoad: false, theme: 'dark' })
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
const UI_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'dev'
const UI_BUILD = typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : ''
const UI_SHA = typeof __GIT_SHA__ !== 'undefined' ? __GIT_SHA__ : ''
const shortStamp = (iso) => (iso ? iso.slice(5, 16).replace('T', ' ') : '')

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="flex h-screen items-center justify-center bg-neutral-900 p-6">
          <div className="max-w-lg rounded-lg border border-danger/60 bg-neutral-950 p-6">
            <h1 className="mb-2 text-lg font-bold text-danger">UI crashed</h1>
            <pre className="mb-4 whitespace-pre-wrap text-xs text-neutral-400">
              {this.state.error && this.state.error.stack
                ? String(this.state.error.stack)
                : String(this.state.error)}
            </pre>
            <button
              className="rounded bg-brand-700 px-3 py-1 text-sm text-brand-fg"
              onClick={() => location.reload()}
            >
              Reload
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

function Login({ onLoggedIn }) {
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  return (
    <div className="flex h-screen items-center justify-center bg-neutral-900">
      <form
        className="w-80 rounded-lg border border-neutral-800 bg-neutral-950 p-6"
        onSubmit={async (e) => {
          e.preventDefault()
          setErr('')
          try {
            await login(password)
            onLoggedIn()
          } catch {
            setErr('wrong password')
          }
        }}
      >
        <div className="mb-4 flex items-center justify-center gap-2">
          <img src={logoUrl} alt="CodingDude logo" className="h-10 w-10 rounded" />
          <h1 className="text-center text-lg font-bold text-brand-400">CodingDude</h1>
        </div>
        <input
          type="password"
          className="mb-3 w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
        />
        {err && <div className="mb-2 text-xs text-danger">{err}</div>}
        <button className="w-full rounded bg-brand-700 px-3 py-2 text-sm font-medium text-brand-fg hover:bg-brand-600">
          Log in
        </button>
      </form>
    </div>
  )
}

function Sidebar({ workdir, setWorkdir, sessions, activeSession, onSelect, onNewSession, width, runningSessions, projects, activeProject, onSelectProject, onAddProject, onDeleteProject }) {
  const [newProjectName, setNewProjectName] = useState(null)
  return (
    <aside className="flex shrink-0 flex-col gap-3 border-r border-neutral-800 bg-neutral-950 p-3" style={{ width }}>
      <div className="flex items-center gap-2">
        <img src={logoUrl} alt="CodingDude logo" className="h-6 w-6 rounded" />
        <h1 className="text-lg font-bold text-brand-400">CodingDude</h1>
      </div>
      <label className="text-xs text-neutral-400">
        Project
        <select
          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-200"
          value={activeProject?.id ?? ''}
          onChange={(e) => {
            const p = projects.find((x) => x.id === Number(e.target.value))
            if (p) onSelectProject(p)
          }}
        >
          <option value="">— select project —</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </label>
      {activeProject && (
        <div className="flex items-center justify-between text-[10px] text-neutral-500">
          <span className="truncate font-mono">{activeProject.workdir}</span>
          <button
            className="text-danger hover:opacity-80"
            title="remove project from list (files are not touched)"
            aria-label="Remove project from list"
            onClick={() => onDeleteProject(activeProject.id)}
          >✕</button>
        </div>
      )}
      <label className="text-xs text-neutral-400">
        Workdir
        <input
          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-200"
          value={workdir}
          onChange={(e) => setWorkdir(e.target.value)}
          placeholder="C:\path\to\project"
        />
      </label>
      {newProjectName !== null ? (
        <div className="flex flex-col gap-1 rounded border border-neutral-700 bg-neutral-900 p-2">
          <input
            className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            placeholder="project name"
            autoFocus
          />
          <div className="truncate text-[10px] text-neutral-500">folder: {workdir || '— set workdir above —'}</div>
          <div className="flex gap-1">
            <button
              className="rounded bg-success px-2 py-1 text-[10px] text-success-fg disabled:opacity-40"
              disabled={!newProjectName.trim() || !workdir.trim()}
              onClick={() => {
                onAddProject(newProjectName.trim(), workdir.trim())
                setNewProjectName(null)
              }}
            >save project</button>
            <button
              className="rounded bg-neutral-700 px-2 py-1 text-[10px] text-ink"
              onClick={() => setNewProjectName(null)}
            >cancel</button>
          </div>
        </div>
      ) : (
        <button
          className="self-start rounded border border-neutral-700 px-2 py-1 text-[10px] text-neutral-400 hover:text-neutral-200"
          onClick={() => setNewProjectName('')}
        >+ New project</button>
      )}
      <button
        className="rounded bg-brand-700 px-2 py-1 text-sm font-medium text-brand-fg hover:bg-brand-600"
        onClick={onNewSession}
      >
        + New session
      </button>
      <div className="flex-1 overflow-y-auto">
        {sessions.map((s) => (
          <button
            key={s.session_id}
            className={`block w-full truncate rounded px-2 py-1 text-left text-sm ${
              s.session_id === activeSession
                ? 'bg-neutral-800 text-brand-300'
                : 'text-neutral-400 hover:bg-neutral-900'
            }`}
            onClick={() => onSelect(s.session_id)}
            title={s.title || s.session_id}
          >
            {s.title || s.session_id.slice(0, 12)}
            {runningSessions.has(s.session_id) && (
              <span className="ml-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-success" />
            )}
            {s.context_limit != null && s.context_tokens != null && s.context_tokens > 0 && (
              <span className="mt-0.5 flex items-center gap-1" title={`Context: ${Math.round((s.context_tokens / s.context_limit) * 100)}% of ${Math.round(s.context_limit / 1000)}k tokens`}>
                <span className="h-0.5 flex-1 overflow-hidden rounded bg-neutral-800">
                  <span
                    className={`block h-full ${
                      s.context_tokens / s.context_limit > 0.8 ? 'bg-danger' : 'bg-brand-600'
                    }`}
                    style={{ width: `${Math.min(100, (s.context_tokens / s.context_limit) * 100)}%` }}
                  />
                </span>
                <span className="text-[9px] text-neutral-500">
                  {Math.round((s.context_tokens / s.context_limit) * 100)}%
                </span>
              </span>
            )}
          </button>
        ))}
      </div>
    </aside>
  )
}

function ToolTimeline({ events }) {
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

function EditBlock({ edit, sessionId, onRevert }) {
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

function AskUserCard({ ask, runId }) {
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

function PendingArtifactCard({ items, onResponded }) {
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

function ApprovalCard({ command, onDecide }) {
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

function PlanCard({ sessionId, onDecide }) {
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

function TreeNode({ node, depth, onOpen }) {
  const [open, setOpen] = useState(depth < 1)
  if (node.type === 'dir') {
    return (
      <div>
        <button
          className="block w-full truncate text-left text-xs text-accent hover:opacity-80"
          style={{ paddingLeft: depth * 10 + 4 }}
          onClick={() => setOpen(!open)}
        >
          {open ? '▾' : '▸'} {node.name}
        </button>
        {open && node.children.map((c) => (
          <TreeNode key={c.path} node={c} depth={depth + 1} onOpen={onOpen} />
        ))}
      </div>
    )
  }
  return (
    <button
      className="block w-full truncate rounded px-1 text-left text-xs text-ink-muted hover:bg-surface hover:text-ink"
      style={{ paddingLeft: depth * 10 + 14 }}
      onClick={() => onOpen(node.path)}
      title={node.path}
    >
      {node.name}
    </button>
  )
}

// R35 #72: tree and editor share tab state, so the workspace state lives in
// one hook (used once, in App); the tree renders in the left rail and the
// editor in the main area.
function useFileWorkspace(sessionId) {
  const [tabs, setTabs] = useState([]) // FileTab[] from editor.ts
  const [draft, setDraft] = useState('')
  const [dirty, setDirty] = useState(false)
  const [notice, setNotice] = useState(null)
  const [diff, setDiff] = useState(null) // {base} when diff view is on
  const active = tabs.find((t) => t.active) || null

  async function openFile(path) {
    try {
      const f = await call(`/sessions/${sessionId}/file?path=${encodeURIComponent(path)}`)
      setTabs(openTab(tabs, { path, content: f.content, mtime: f.mtime }))
      setDraft(f.content)
      setDirty(false)
      setNotice(null)
      setDiff(null)
    } catch (e) {
      setNotice(`cannot open ${path}: ${e.message}`)
    }
  }
  return { sessionId, tabs, setTabs, draft, setDraft, dirty, setDirty, notice, setNotice, diff, setDiff, active, openFile }
}
// Left rail: full-height file tree for the active session.
function FileTree({ sessionId, onOpen }) {
  const [tree, setTree] = useState(null)
  useEffect(() => {
    if (!sessionId) return
    let stop = false
    async function poll() {
      try {
        const t = await call(`/sessions/${sessionId}/tree`)
        if (!stop) setTree(t)
      } catch { /* transient */ }
      if (!stop) setTimeout(poll, 10000)
    }
    poll()
    return () => { stop = true }
  }, [sessionId])
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-1">
      {sessionId && tree ? tree.children.map((c) => (
        <TreeNode key={c.path} node={c} depth={0} onOpen={onOpen} />
      )) : <div className="text-neutral-600">{sessionId ? 'loading…' : 'no session'}</div>}
    </div>
  )
}

// Main area: tab strip + Monaco editor / diff for the shared workspace.
function EditorPane({ ws, onAsk }) {
  const { sessionId, tabs, setTabs, draft, setDraft, dirty, setDirty, notice, setNotice, diff, setDiff, active, openFile } = ws
  const [selection, setSelection] = useState('')

  function activate(path) {
    const t = tabs.find((x) => x.path === path)
    if (!t) return
    setTabs(tabs.map((x) => ({ ...x, active: x.path === path })))
    setDraft(t.content)
    setDirty(false)
    setNotice(null)
    setDiff(null)
  }

  function close(path) {
    const next = closeTab(tabs, path)
    setTabs(next)
    const nowActive = next.find((t) => t.active)
    setDraft(nowActive ? nowActive.content : '')
    setDirty(false)
    setNotice(null)
    setDiff(null)
  }

  async function save() {
    if (!active) return
    try {
      const r = await call(`/sessions/${sessionId}/file`, {
        method: 'PUT',
        body: JSON.stringify({
          path: active.path, content: draft, expected_mtime: active.mtime,
        }),
      })
      setTabs(tabs.map((t) => (t.path === active.path
        ? { ...t, content: draft, mtime: r.mtime }
        : t)))
      setDirty(false)
      setNotice('saved ✓')
    } catch (e) {
      setNotice(e.message.includes('409')
        ? `${active.path} changed on disk since you opened it — reload to pick up the agent's version, then re-apply your edit.`
        : `save failed: ${e.message}`)
    }
    setTimeout(() => setNotice(null), 4000)
  }

  async function toggleDiff() {
    if (diff) { setDiff(null); return }
    if (!active) return
    try {
      const r = await call(`/sessions/${sessionId}/file_diff?path=${encodeURIComponent(active.path)}`)
      setDiff({ base: r.base })
    } catch (e) {
      setNotice(`diff failed: ${e.message}`)
      setTimeout(() => setNotice(null), 4000)
    }
  }

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-neutral-500">
        Open a file from the explorer or pick a session to chat.
      </div>
    )
  }
  if (tabs.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-neutral-500">
        Open a file from the explorer to start editing.
      </div>
    )
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1 p-2">
      <div className="flex items-center gap-0.5 overflow-x-auto">
        {tabs.map((t) => (
          <div key={t.path} className={`group flex items-center rounded-t border-b-2 px-2 py-0.5 text-[10px] ${t.active ? 'border-brand bg-neutral-800 text-ink' : 'border-transparent bg-neutral-900 text-ink-muted'}`}>
            <button className="max-w-40 truncate font-mono" onClick={() => activate(t.path)} title={t.path}>
              {t.path.split('/').pop()}
            </button>
            <button className="ml-1 text-neutral-500 hover:text-danger" onClick={() => close(t.path)}>×</button>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between">
        <span className="truncate font-mono text-[10px] text-brand-300">{active?.path}</span>
        <div className="flex gap-1">
          <button
            className="rounded bg-brand-700 px-2 py-0.5 text-[10px] text-brand-fg disabled:opacity-40"
            disabled={!dirty}
            onClick={save}
          >save</button>
          <button
            className="rounded bg-neutral-700 px-2 py-0.5 text-[10px] text-ink"
            onClick={() => active && openFile(active.path)}
          >reload</button>
          <button
            className={`rounded px-2 py-0.5 text-[10px] text-ink ${diff ? 'bg-brand-700 text-brand-fg' : 'bg-neutral-700'}`}
            disabled={!active}
            onClick={toggleDiff}
          >diff vs HEAD</button>
        </div>
      </div>
      {notice && <div className="text-[10px] text-brand-400">{notice}</div>}
      <div className="min-h-0 flex-1 overflow-hidden rounded border border-neutral-700">
        {diff
          ? (
            <CodeDiff
              path={active?.path || ''}
              original={diff.base}
              modified={draft}
              height="100%"
            />
          )
          : (
            <CodeEditor
              path={active?.path || ''}
              value={draft}
              onChange={(v) => { setDraft(v); setDirty(true) }}
              onSelectionChange={setSelection}
              height="100%"
            />
          )}
      </div>
      {selection.trim() && onAsk && (
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-neutral-500">
            {selection.split('\n').length} line{selection.split('\n').length === 1 ? '' : 's'} selected
          </span>
          {ACTIONS.map((a) => (
            <button
              key={a.id}
              className="rounded bg-neutral-700 px-2 py-0.5 text-[10px] text-ink hover:bg-brand-700 hover:text-brand-fg"
              onClick={() => {
                const prompt = buildActionPrompt(a.id, active?.path || '', selection)
                if (!prompt) return
                setSelection('')
                onAsk(prompt)
              }}
            >{a.label}</button>
          ))}
          <button
            className="rounded px-1 text-[10px] text-neutral-500 hover:text-danger"
            onClick={() => setSelection('')}
          >×</button>
        </div>
      )}
    </div>
  )
}


function Terminal({ sessionId }) {
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

function Notes({ sessionId, workdir }) {
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

function Artifacts({ sessionId }) {
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

// R50 #209: user-managed LLM configuration editor.
// Field-level edits stay in a local draft; Save PUTs the whole lineup and
// shows the server's validation error verbatim (it is the source of truth).
// Config fields must be stable module-level components: defining them inside
// ModelsConfig gave them a new identity on every render (the dock's 4s config
// poll re-renders constantly), remounting the inputs and stealing focus.
function CfgTextField({ label, value, onChange, placeholder }) {
  return (
    <label className="flex items-center gap-2 text-[11px]">
      <span className="w-32 shrink-0 text-neutral-500">{label}</span>
      <input
        className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
        value={value ?? ''}
        placeholder={placeholder || ''}
        list="provider-model-suggest"
        onChange={(e) => onChange(e.target.value || null)}
      />
    </label>
  )
}

function CfgNumField({ label, value, onChange }) {
  return (
    <label className="flex items-center gap-2 text-[11px]">
      <span className="w-32 shrink-0 text-neutral-500">{label}</span>
      <input
        type="number"
        className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      />
    </label>
  )
}

function ModelsConfig({ data, setData }) {
  const cfg = data.config
  // Hooks must run unconditionally — the early returns below (error/loading)
  // used to come before the keys/verify state, changing the hook count
  // between renders and crashing React (#310).
  const [draft, setDraft] = useState(null)
  const [msg, setMsg] = useState(null)
  const [keys, setKeys] = useState(null) // {provider: {key, base_url, env_var, clear, del}}
  const [newProv, setNewProv] = useState({ name: '', key: '', base_url: '', env_var: '' })
  const [verify, setVerify] = useState(null)
  const [verifying, setVerifying] = useState(false)

  if (data.configError) {
    return <div className="rounded border border-danger/40 bg-danger/10 p-3 text-xs text-danger">{data.configError}</div>
  }
  if (!cfg) {
    return <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">Loading model configuration…</div>
  }

  const model = draft ?? JSON.parse(JSON.stringify(cfg.models))
  const set = (k, v) => setDraft({ ...model, [k]: v })

  // #212: providers are user-defined — the draft edits name/base_url/key per
  // provider; blank key keeps the stored one, the clear flag removes it.
  const keyDraft = keys ?? Object.fromEntries(
    Object.entries(cfg.providers || {}).map(([n]) => [n, {
      key: '',
      base_url: cfg.provider_defs?.[n]?.base_url || '',
      env_var: cfg.provider_defs?.[n]?.env_var || '',
      clear: false,
      del: false,
    }])
  )
  const setKey = (n, patch) => setKeys({ ...keyDraft, [n]: { ...keyDraft[n], ...patch } })

  const newProvDirty = !!(newProv.name || newProv.key || newProv.base_url)
  const save = async () => {
    setMsg(null)
    try {
      const body = {}
      if (draft) body.models = model
      if (keys !== null || newProvDirty) {
        body.providers = {}
        for (const [n, e] of Object.entries(keyDraft)) {
          if (e.del) { body.providers[n] = null; continue }
          const def = {}
          if (e.clear) def.api_key = null // drop the stored key on save
          else if (e.key) def.api_key = e.key
          if ((e.base_url || '') !== (cfg.provider_defs?.[n]?.base_url || ''))
            def.base_url = e.base_url || null
          if ((e.env_var || '') !== (cfg.provider_defs?.[n]?.env_var || ''))
            def.env_var = e.env_var || null
          if (Object.keys(def).length) body.providers[n] = def
        }
        if (newProv.name && (newProv.key || newProv.base_url)) {
          body.providers[newProv.name.trim()] = {
            api_key: newProv.key || null,
            base_url: newProv.base_url || null,
            env_var: newProv.env_var || null,
          }
        }
      }
      const r = await call('/config/models', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      setData((d) => ({ ...d, config: r.effective }))
      setDraft(null)
      setKeys(null)
      setNewProv({ name: '', key: '', base_url: '', env_var: '' })
      setMsg({ ok: true, text: 'Saved — applies from the next run.' })
    } catch (err) {
      setMsg({ ok: false, text: String(err instanceof Error ? err.message : err) })
    }
  }

  const testKeys = async () => {
    setVerifying(true); setVerify(null); setMsg(null)
    try {
      const r = await call('/config/verify')
      setVerify(r.providers)
    } catch (err) {
      setMsg({ ok: false, text: String(err instanceof Error ? err.message : err) })
    } finally { setVerifying(false) }
  }

  const field = (label, k, placeholder) => (
    <CfgTextField key={k} label={label} value={model[k]} placeholder={placeholder} onChange={(v) => set(k, v)} />
  )
  const numField = (label, k) => (
    <CfgNumField key={k} label={label} value={model[k]} onChange={(v) => set(k, v)} />
  )

  return (
    <div className="flex h-full flex-col gap-3 overflow-auto p-1 text-ink">
      <div className="text-[10px] text-neutral-500">
        ~/.codingdude/config.toml — provider keys are stored there, masked in this UI.
      </div>
      {(cfg.warnings || []).length > 0 && (
        <div className="rounded border border-warning/40 bg-warning/10 px-2 py-1 text-[11px] text-warning">
          {(cfg.warnings || []).map((w) => <div key={w}>{w}</div>)}
        </div>
      )}
      <div className="space-y-1.5 rounded border border-line bg-surface p-3">
        <div className="text-[10px] uppercase tracking-wide text-ink-muted">Model lineup (provider:model)</div>
        {field('main', 'main')}
        {field('subagent', 'subagent')}
        {field('fallback', 'fallback')}
        {field('fallback base url', 'fallback_base_url', 'optional endpoint override')}
        <div className="text-[10px] text-neutral-500">
          Z.AI has two plans with different endpoints. GLM Coding Plan keys are rejected by the
          standard API —{' '}
          <button
            type="button"
            className="text-accent underline hover:opacity-80"
            onClick={() => set('fallback_base_url', 'https://api.z.ai/api/coding/paas/v4')}
          >set the coding-plan endpoint</button>
        </div>
        {field('vision', 'vision', 'e.g. zai:glm-5v (optional)')}
        <label className="flex items-center gap-2 text-[11px]">
          <span className="w-32 shrink-0 text-neutral-500">thinking</span>
          <select
            className="min-w-0 flex-1 rounded border border-line bg-surface px-1 py-0.5 font-mono text-[11px] text-ink"
            value={model.thinking ?? ''}
            onChange={(e) => set('thinking', e.target.value || null)}
          >
            <option value="">(provider default)</option>
            <option value="off">off</option>
            {(cfg.thinking_levels || []).map((lvl) => (
              <option key={lvl} value={lvl}>{lvl}</option>
            ))}
          </select>
        </label>
        {numField('max tokens', 'max_tokens')}
        {numField('context limit', 'context_limit')}
        {numField('request limit', 'request_limit')}
      </div>

      <div className="space-y-1.5 rounded border border-line bg-surface p-3">
        <div className="text-[10px] uppercase tracking-wide text-ink-muted">Providers</div>
        <div className="text-[10px] text-neutral-500">
          User-defined OpenAI-compatible providers. A name with a base URL makes
          `name:model` bindings work everywhere. Keys stored in
          ~/.codingdude/config.toml, never displayed; blank keeps a set key.
        </div>
        <datalist id="provider-model-suggest">
          {(cfg.provider_prefixes || []).map((p) => (
            <option key={p} value={`${p}:`} />
          ))}
        </datalist>
        {Object.entries(keyDraft).map(([name, e]) => e.del ? null : (
          <div key={name} className="flex flex-wrap items-center gap-2 text-[11px]">
            <span className="w-28 shrink-0 font-mono text-neutral-500">{name}</span>
            <input
              type="password"
              className="w-40 min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
              value={e.key}
              placeholder={e.clear ? 'cleared on save' : (cfg.providers?.[name] ? '● set — leave blank to keep' : 'api key')}
              onChange={(ev) => setKey(name, { key: ev.target.value, clear: false })}
            />
            <input
              className="w-48 min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
              value={e.base_url}
              placeholder="base URL (https://…/v1)"
              onChange={(ev) => setKey(name, { base_url: ev.target.value })}
            />
            <input
              className="w-32 min-w-0 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
              value={e.env_var}
              placeholder="env var (optional)"
              onChange={(ev) => setKey(name, { env_var: ev.target.value })}
            />
            {cfg.providers?.[name] && (
              <button type="button" title={e.clear ? 'undo clear' : 'clear stored key on save'}
                className="rounded border border-line px-1.5 py-0.5 text-[10px] text-neutral-400 hover:text-danger"
                onClick={() => setKey(name, { clear: !e.clear, key: '' })}
              >{e.clear ? 'undo' : 'clear'}</button>
            )}
            <button type="button" title="delete this provider"
              className="rounded border border-line px-1.5 py-0.5 text-[10px] text-neutral-400 hover:text-danger"
              onClick={() => setKey(name, { del: true })}
            >remove</button>
            {verify && name in verify && (
              <span className={verify[name].ok ? 'text-success' : 'text-danger'}>
                {verify[name].ok ? '✓ auth ok' : `✗ ${verify[name].status || ''} ${verify[name].detail || 'failed'}`.slice(0, 60)}
              </span>
            )}
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span className="w-28 shrink-0 text-[10px] uppercase text-neutral-500">add</span>
          <input
            className="w-28 min-w-0 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
            placeholder="name" value={newProv.name}
            onChange={(e) => setNewProv({ ...newProv, name: e.target.value.replace(/[^A-Za-z0-9_-]/g, '').replace(/^[^A-Za-z0-9]+/, '') })}
          />
          <input
            type="password"
            className="w-40 min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
            placeholder="api key" value={newProv.key}
            onChange={(e) => setNewProv({ ...newProv, key: e.target.value })}
          />
          <input
            className="w-48 min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
            placeholder="base URL (https://…/v1)" value={newProv.base_url}
            onChange={(e) => setNewProv({ ...newProv, base_url: e.target.value })}
          />
          <input
            className="w-32 min-w-0 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
            placeholder="env var (optional)" value={newProv.env_var || ''}
            onChange={(e) => setNewProv({ ...newProv, env_var: e.target.value })}
          />
        </div>
        <button
          type="button"
          className="rounded border border-line px-2 py-0.5 text-[11px] text-neutral-400 hover:text-ink disabled:opacity-40"
          disabled={verifying}
          onClick={testKeys}
        >{verifying ? 'Testing…' : 'Test keys'}</button>
      </div>

      {msg && (
        <div className={`rounded px-2 py-1 text-[11px] ${msg.ok ? 'bg-success/15 text-brand-300' : 'bg-danger/15 text-danger'}`}>
          {msg.text}
        </div>
      )}
      <div className="flex gap-2">
        <button
          className="rounded bg-brand-600 px-3 py-1 text-[11px] text-white hover:bg-brand-500 disabled:opacity-40"
          disabled={!draft && keys === null && !newProvDirty}
          onClick={save}
        >Save</button>
        <button
          className="rounded border border-line px-3 py-1 text-[11px] text-neutral-400 hover:text-ink disabled:opacity-40"
          disabled={!draft && !keys}
          onClick={() => { setDraft(null); setKeys(null); setMsg(null); setVerify(null) }}
        >Revert</button>
      </div>
    </div>
  )
}

function Planning({ workdir }) {
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

// R35 #72: bottom dock — VS Code panel position. Processes comes in as a
// prop (App polls it); it used to be a bare-identifier crash in this scope.
function DockPanel({ sessionId, refreshKey, diffBadge, artifactsPending = 0, workdir, processes, height, onResizeHeight, focusDiff = 0, activePath = '', onAsk }) {
  const [repoQuestion, setRepoQuestion] = useState('')
  const tabs = ['Diff', 'Graph', 'Planning', 'Artifacts', 'Notes', 'Renders', 'Terminal', 'Output', 'Waterfall', 'Trace', 'Cost', 'Memory', 'MCP', 'Config', 'Standards']
  const [tab, setTab] = useState('Diff')
  const [data, setData] = useState({})

  // R35 #75: "review agent changes" bumps focusDiff to switch to the Diff tab.
  useEffect(() => {
    if (focusDiff > 0) setTab('Diff')
  }, [focusDiff])

  useEffect(() => {
    // R50: model config is session-independent — load it without a session.
    if (tab === 'Config' && !sessionId) {
      ;(async () => {
        try {
          const r = await call('/config/models')
          setData((d) => ({ ...d, config: r, configError: undefined }))
        } catch (err) {
          setData((d) => ({ ...d, configError: String(err instanceof Error ? err.message : err) }))
        }
      })()
      return
    }
    if (!sessionId || tab === 'Standards' || tab === 'Terminal' || tab === 'Planning') return
    let stop = false
    async function poll() {
      try {
        if (tab === 'Diff') { const r = await call(`/sessions/${sessionId}/diff`); setData((d) => ({ ...d, diff: r.diff, diffSummary: r.summary || [], impact: r.impact || null })) }
        if (tab === 'Graph' && activePath) {
          try {
            const g = await call(`/sessions/${sessionId}/callgraph?path=${encodeURIComponent(activePath)}`)
            setData((d) => ({ ...d, callgraph: g, callgraphPath: activePath, graphError: undefined }))
          } catch (err) {
            // #99: a 422 (unparseable file) must reach the user verbatim,
            // not masquerade as "no callable symbols found".
            if (activePath === (data.callgraphPath || activePath)) setData((d) => ({ ...d, graphError: String(err instanceof Error ? err.message : err) }))
          }
          try {
            const t = await call(`/sessions/${sessionId}/trust?path=${encodeURIComponent(activePath)}`)
            setData((d) => ({ ...d, trust: t, trustPath: activePath }))
          } catch { /* trust is supplementary; callgraph errors already surfaced */ }
          if (activePath.endsWith('.py')) {
            try {
              const cf = await call(`/sessions/${sessionId}/cfg?path=${encodeURIComponent(activePath)}`)
              setData((d) => ({ ...d, cfgFunctions: cf.functions || [], cfgFunctionsPath: activePath, cfg: undefined, cfgFn: undefined, cfgError: undefined }))
            } catch (err) {
              setData((d) => ({ ...d, cfgFunctions: [], cfgFunctionsPath: activePath, cfgError: String(err instanceof Error ? err.message : err) }))
            }
          }
        }
        if (tab === 'Graph' && !activePath) {
          const s = await call(`/sessions/${sessionId}/structure`)
          const a = await call(`/sessions/${sessionId}/archmap`)
          setData((d) => ({ ...d, structure: s, archmap: a }))
        }
        if (tab === 'Cost') { const u = await call(`/sessions/${sessionId}/usage`); setData((d) => ({ ...d, usage: u })) }
        if (tab === 'Output') {
          const runs = await call(`/sessions/${sessionId}/runs`)
          const tr = await call(`/sessions/${sessionId}/trace?limit=300`)
          setData((d) => ({ ...d, runs, runEvents: tr }))
        }
        if (tab === 'Config') { const r = await call('/config/models'); setData((d) => ({ ...d, config: r, configError: undefined })) }
        if (tab === 'Memory') { const m = await call('/memory'); setData((d) => ({ ...d, memory: m })) }
        if (tab === 'MCP') { const m = await api.listMcp(sessionId); setData((d) => ({ ...d, mcp: m })) }
        if (tab === 'Trace') {
          const tr = await call(`/sessions/${sessionId}/trace?limit=50`)
          const cps = await call(`/sessions/${sessionId}/checkpoints`)
          setData((d) => ({ ...d, trace: tr, checkpoints: cps }))
        }
        if (tab === 'Artifacts') { const r = await call(`/sessions/${sessionId}/artifacts`); setData((d) => ({ ...d, artifacts: r })) }
        if (tab === 'Renders') {
          const r = await call(`/sessions/${sessionId}/renders`)
          setData((d) => ({ ...d, renders: r.renders, renderStart: r.session_start }))
        }
      } catch { /* transient */ }
      if (!stop) setTimeout(poll, 4000)
    }
    poll()
    return () => { stop = true }
  }, [sessionId, tab, activePath])

  async function toggleServer(name, disabled) {
    await api.toggleMcp(sessionId, name, disabled).catch(() => {})
    const m = await api.listMcp(sessionId)
    setData((d) => ({ ...d, mcp: m }))
  }

  const [review, setReview] = useState(null) // {findings} | 'running'
  // Output tab: which run to show (null = newest).
  const [selRun, setSelRun] = useState(null)
  async function runReview() {
    setReview({ running: true })
    try {
      const r = await call(`/sessions/${sessionId}/review`, { method: 'POST' })
      setReview({ findings: r.findings })
    } catch (e) {
      setReview({ findings: `review failed: ${e.message}` })
    }
  }


  // Standards sub-tab state: directives editor, skills manager, review checklist.
  const [stdMode, setStdMode] = useState('directives')
  const [directivesDraft, setDirectivesDraft] = useState(null)
  const [skillList, setSkillList] = useState(null)
  const [reviewChecklist, setReviewChecklist] = useState(null)
  const [editingSkill, setEditingSkill] = useState(null)
  const [savedMsg, setSavedMsg] = useState('')

  useEffect(() => {
    if (tab !== 'Standards' || !sessionId) return
    call(`/sessions/${sessionId}/standards`)
      .then((d) => setReviewChecklist(d.review_checklist))
      .catch(() => setReviewChecklist('unavailable'))
    call('/skills/detail').then(setSkillList).catch(() => setSkillList([]))
    call('/directives')
      .then((d) => setDirectivesDraft((cur) => cur ?? d.content))
      .catch(() => setDirectivesDraft(''))
  }, [tab, sessionId])

  async function saveDirectives() {
    await call('/directives', { method: 'PUT', body: JSON.stringify({ content: directivesDraft }) })
    setSavedMsg('directives saved — enforced from the next run')
    setTimeout(() => setSavedMsg(''), 2500)
  }

  async function startEditSkill(name) {
    const list = await call('/skills/detail')
    setEditingSkill(list.find((s) => s.name === name) || null)
  }

  async function saveSkill() {
    if (!editingSkill?.name) return
    await call(`/skills/detail/${encodeURIComponent(editingSkill.name)}`, {
      method: 'PUT',
      body: JSON.stringify({ description: editingSkill.description, body: editingSkill.body }),
    })
    setEditingSkill(null)
    call('/skills/detail').then(setSkillList).catch(() => {})
  }

  async function deleteSkill(name) {
    // Auth is the HttpOnly session cookie — no bearer header exists (L13).
    await fetch(`/api/skills/detail/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }).then((r) => r.json())
    setSkillList((list) => list.filter((s) => s.name !== name))
  }

  let body = (
    <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">
      Select a session to see diffs, files, cost and trace.
    </div>
  )
  if (tab === 'Standards') {
    const modes = ['directives', 'skills', 'checklist']
    body = (
      <div className="flex h-full flex-col gap-2">
        <div className="flex gap-1">
          {modes.map((m) => (
            <button
              key={m}
              className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${stdMode === m ? 'bg-neutral-800 text-brand-300' : 'text-neutral-500 hover:text-neutral-300'}`}
              onClick={() => setStdMode(m)}
            >{m}</button>
          ))}
        </div>
        {savedMsg && <div className="rounded bg-success/15 px-2 py-1 text-[10px] text-brand-300">{savedMsg}</div>}

        {stdMode === 'directives' && (
          <div className="flex min-h-0 flex-1 flex-col gap-1">
            <div className="text-[10px] text-neutral-500">
              ~/.codingdude/DIRECTIVES.md — enforced on every run (project AGENT.md adds on top)
            </div>
            <div className="min-h-0 flex-1 overflow-hidden rounded border border-neutral-700">
              <CodeEditor
                path="DIRECTIVES.md"
                value={directivesDraft ?? ''}
                onChange={setDirectivesDraft}
                height="100%"
              />
            </div>
            <button
              className="self-start rounded bg-brand-700 px-3 py-1 text-xs text-brand-fg hover:bg-brand-600"
              onClick={saveDirectives}
            >Save directives</button>
          </div>
        )}

        {stdMode === 'skills' && !editingSkill && (
          <div className="flex flex-1 flex-col gap-1 overflow-y-auto">
            <button
              className="self-start rounded bg-brand-700 px-2 py-1 text-[10px] text-brand-fg"
              onClick={() => setEditingSkill({ name: 'new-skill', description: '', body: '' })}
            >+ new skill</button>
            {skillList && skillList.map((s) => (
              <div key={s.name} className="flex items-start justify-between gap-1 rounded bg-neutral-900 p-1">
                <div className="min-w-0">
                  <div className="text-xs text-neutral-200">{s.name}</div>
                  <div className="truncate text-[10px] text-neutral-500">{s.description}</div>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button className="text-[10px] text-accent" onClick={() => startEditSkill(s.name)}>edit</button>
                  <button className="text-[10px] text-danger" onClick={() => deleteSkill(s.name)}>del</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {stdMode === 'skills' && editingSkill && (
          <div className="flex min-h-0 flex-1 flex-col gap-1">
            <input
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
              value={editingSkill.name}
              onChange={(e) => setEditingSkill({ ...editingSkill, name: e.target.value })}
              placeholder="skill-name"
            />
            <input
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
              value={editingSkill.description}
              onChange={(e) => setEditingSkill({ ...editingSkill, description: e.target.value })}
              placeholder="when should the agent use this skill?"
            />
            <div className="min-h-0 flex-1 overflow-hidden rounded border border-neutral-700">
              <CodeEditor
                path={`${editingSkill.name}.md`}
                value={editingSkill.body}
                onChange={(v) => setEditingSkill({ ...editingSkill, body: v })}
                height="100%"
              />
            </div>
            <div className="flex gap-1">
              <button className="rounded bg-brand-700 px-3 py-1 text-xs text-brand-fg" onClick={saveSkill}>save skill</button>
              <button className="rounded bg-neutral-700 px-3 py-1 text-xs text-ink" onClick={() => setEditingSkill(null)}>cancel</button>
            </div>
          </div>
        )}

        {stdMode === 'checklist' && (
          <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap rounded bg-neutral-900 p-2 text-[11px] text-neutral-400">
            {reviewChecklist ?? 'loading…'}
          </pre>
        )}
      </div>
    )
  } else if (tab === 'Output') {
    // #75/#77: run output — one run's activity stream plus the run list.
    const groups = groupEventsByRun(data.runEvents || [])
    const runId = pickRunId(groups, selRun)
    const events = groups[runId] || []
    const statusOf = (rid) => (data.runs || []).find((r) => r.run_id === rid)?.status
    const statusColor = (s) => s === 'completed' ? 'text-success'
      : s === 'failed' ? 'text-danger'
      : s === 'interrupted' ? 'text-warning'
      : 'text-accent'
    body = (
      <div className="flex h-full min-h-0 flex-col gap-2">
        <div className="flex flex-wrap gap-1">
          {(data.runs || []).map((r) => (
            <button
              key={r.run_id}
              className={`rounded px-2 py-0.5 font-mono text-[10px] ${r.run_id === runId ? 'bg-neutral-800 text-brand-300' : 'text-neutral-500 hover:text-neutral-300'}`}
              onClick={() => setSelRun(r.run_id)}
              title={`${r.status}${r.exit_code != null ? ` (exit ${r.exit_code})` : ''} — started ${r.started_at}`}
            >
              {r.run_id} <span className={statusColor(r.status)}>{r.status}</span>
            </button>
          ))}
          {(!data.runs || !data.runs.length) && (
            <span className="text-[10px] text-ink-muted">no runs recorded yet</span>
          )}
        </div>
        {runId && (
          <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto font-mono text-[10px]">
            {events.slice().reverse().map((e, i) => (
              <div key={i} className="truncate rounded px-1 hover:bg-surface text-ink-muted">
                <span className="text-ink-muted">{(e.ts || '').slice(11, 19)}</span> {e.type}{' '}
                {e.command || e.tool_name || e.delta || ''}
              </div>
            ))}
            {!events.length && <div className="px-1 text-ink-muted">no events for this run (pre-R31 trace or dropped)</div>}
          </div>
        )}
        {runId && <div className={`text-[10px] ${statusColor(statusOf(runId))}`}>run {runId} — {statusOf(runId) || 'unknown'}</div>}
        {runId && (
          <div className="rounded border border-line bg-surface p-1">
            <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wide text-ink-muted">
              <span>tour of this run</span>
              {onAsk && (
                <button
                  className="ml-auto rounded bg-brand-700 px-2 py-0.5 text-[10px] normal-case text-brand-fg"
                  onClick={() => {
                    const steps = buildTour(events)
                    const prompt = buildDesignDocPrompt(`run ${runId} (${statusOf(runId)})`, steps)
                    if (prompt) onAsk(prompt)
                  }}
                >draft design doc</button>
              )}
            </div>
            {(() => {
              const steps = buildTour(events)
              if (!steps.length) return <div className="px-1 text-[10px] text-ink-muted">nothing narratable happened in this run.</div>
              return (
                <ol className="list-inside list-decimal space-y-0.5 px-1 text-[11px] text-neutral-300">
                  {steps.map((s, i) => <li key={i}>{s.label}</li>)}
                </ol>
              )
            })()}
          </div>
        )}
      </div>
    )
  } else if (tab === 'Waterfall') {
    // #84 (R38): span timeline of the selected run's tool calls, edits, gates.
    const groups = groupEventsByRun(data.runEvents || [])
    const wfRunId = pickRunId(groups, selRun)
    const { spans, total } = buildSpans(groups[wfRunId] || [])
    const kindColor = (k) => k === 'edit' ? 'bg-brand-500' : k === 'gate' ? 'bg-warning' : k === 'tool' ? 'bg-accent' : 'bg-neutral-600'
    body = (
      <div className="flex h-full min-h-0 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-1">
          {(data.runs || []).map((r) => (
            <button
              key={r.run_id}
              className={`rounded px-2 py-0.5 font-mono text-[10px] ${r.run_id === wfRunId ? 'bg-neutral-800 text-brand-300' : 'text-neutral-500 hover:text-neutral-300'}`}
              onClick={() => setSelRun(r.run_id)}
            >{r.run_id}</button>
          ))}
          {total > 0 && <span className="ml-auto text-[10px] text-ink-muted">{total.toFixed(1)}s</span>}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {spans.length > 0 && total > 0 && (
            <div className="relative space-y-1">
              {spans.map((s, i) => (
                <div key={i} className="flex items-center gap-2 font-mono text-[10px]">
                  <span className="w-8 shrink-0 text-right text-ink-muted">{s.start.toFixed(1)}s</span>
                  <div className="relative h-3 min-w-0 flex-1 rounded bg-neutral-900">
                    <div
                      className={`absolute h-3 rounded ${kindColor(s.kind)} ${s.kind !== 'tool' || s.end === s.start ? 'w-1.5' : ''} opacity-80`}
                      style={s.kind === 'tool' && s.end > s.start ? {
                        left: `${(s.start / total) * 100}%`,
                        width: `${Math.max(((s.end - s.start) / total) * 100, 1)}%`,
                      } : { left: `${(s.start / total) * 100}%` }}
                      title={s.unclosed ? `${s.label} (unclosed)` : `${s.label}: ${s.start.toFixed(1)}s → ${s.end.toFixed(1)}s`}
                    />
                  </div>
                  <span className="w-40 shrink-0 truncate text-neutral-300" title={s.label}>{s.label}{s.unclosed ? ' ?' : ''}</span>
                </div>
              ))}
            </div>
          )}
          {!spans.length && <div className="text-[10px] text-ink-muted">no timed events for this run</div>}
        </div>
      </div>
    )
  } else if (tab === 'Trace') {
    const colors = {
      GATE_REQUEST: 'text-warning', RUN_ERROR: 'text-danger',
      RUN_FINISHED: 'text-brand-400', TOOL_CALL_START: 'text-accent',
      TOOL_CALL_END: 'text-accent', PLAN_PROPOSED: 'text-accent',
      USER_PROMPT: 'text-neutral-300',
    }
    body = (
      <div className="space-y-2">
        <div className="space-y-0.5 font-mono text-[10px]">
          {(data.trace || []).slice().reverse().map((e, i) => (
            <div key={i} className={`truncate rounded px-1 hover:bg-surface ${colors[e.type] || 'text-ink-muted'}`}>
              <span className="text-ink-muted">{(e.ts || '').slice(11, 19)}</span> {e.type}{' '}
              {e.command || e.tool_name || e.delta || ''}
            </div>
          ))}
          {(!data.trace || !data.trace.length) && (
            <div className="px-1 text-ink-muted">no events yet</div>
          )}
        </div>
        {data.checkpoints && data.checkpoints.length > 0 && (
          <div className="space-y-1 border-t border-neutral-800 pt-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-neutral-400">Checkpoints</div>
            {data.checkpoints.map((c) => (
              <div key={c.id} className="rounded bg-neutral-900 p-1">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] text-neutral-300">{c.id.slice(0, 17)}</span>
                  <div className="flex gap-1">
                    <button
                      className="rounded bg-accent px-1.5 py-0.5 text-[9px] text-accent-fg"
                      onClick={() => call(`/checkpoints/${sessionId}/${c.id}/rewind`, { method: 'POST', body: '{}' }).catch(() => {})}
                    >rewind</button>
                  </div>
                </div>
                <div className="text-[9px] text-neutral-500">{c.files.join(', ')}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  } else if (tab === 'Terminal') {
    body = <Terminal sessionId={sessionId} />
  } else if (tab === 'Processes') {
    body = (
      <div className="space-y-1 overflow-y-auto p-3 text-xs">
        {!sessionId && <p className="text-ink-muted">No active session.</p>}
        {sessionId && activeProcesses(processes || []).length === 0 && (
          <p className="text-ink-muted">No running processes this session.</p>
        )}
        {activeProcesses(processes || []).map((p) => (
          <div key={`${p.pid}:${p.started_at}`} className="rounded border border-neutral-800 p-2">
            <div className="flex items-center gap-2">
              <span className="text-ink-muted">[{p.pid}]</span>
              <span className={p.status === 'running' ? 'text-green-500' : 'text-neutral-500'}>
                {p.status === 'running' ? '● running' : `exited (${p.exit_code ?? '?'})`}
              </span>
              {p.background && <span className="text-amber-500">background</span>}
              <span className="ml-auto text-neutral-600">{(p.started_at || '').replace('T', ' ').slice(0, 19)}</span>
            </div>
            <div className="mt-1 break-all font-mono text-[11px] text-ink-muted">{p.command}</div>
          </div>
        ))}
      </div>
    )
  } else if (tab === 'Planning') {
    body = <Planning workdir={workdir} />
  } else if (tab === 'Config') {
    body = <ModelsConfig data={data} setData={setData} />
  } else if (tab === 'Artifacts') {
    body = <Artifacts sessionId={sessionId} />
  } else if (tab === 'Notes') {
    body = <Notes sessionId={sessionId} workdir={workdir} />
  } else if (tab === 'MCP' && data.mcp) {
    body = (
      <div className="space-y-1">
        {data.mcp.length === 0 && <div className="text-neutral-600">no MCP servers configured</div>}
        {data.mcp.map((s) => (
          <div key={s.name} className="flex items-center justify-between rounded bg-neutral-900 p-1">
            <span className={s.disabled ? 'text-neutral-600 line-through' : 'text-neutral-300'}>
              {s.name} <span className="text-neutral-600">({s.config.command})</span>
            </span>
            <button
              className={s.disabled ? 'text-brand-500 hover:text-brand-300' : 'text-danger hover:opacity-80'}
              onClick={() => toggleServer(s.name, !s.disabled)}
            >{s.disabled ? 'enable' : 'disable'}</button>
          </div>
        ))}
        <div className="text-neutral-600">config: ~/.codingdude/mcp.json (global) + .codingdude/mcp.json (project)</div>
      </div>
    )
  } else if (tab === 'Graph') {
    body = activePath ? (
      <div className="rounded border border-line bg-surface">
        <div className="flex items-center gap-3 border-b border-line px-2 py-1 font-mono text-[10px]">
          <span className="text-brand-300">{activePath}</span>
          <span className="ml-auto uppercase tracking-wide text-ink-muted">call graph</span>
        </div>
        <div className="max-h-[70vh] overflow-auto p-2">
          {(() => {
            const view = graphView(data.callgraph, data.callgraphPath, activePath, data.graphError)
            if (view.kind === 'error') return <div className="text-xs text-danger">{view.error}</div>
            if (view.kind === 'loading') return <div className="text-xs text-ink-muted">Analyzing…</div>
            if (view.kind === 'empty') return <div className="text-xs text-ink-muted">No callable symbols found in this file.</div>
            return <Mermaid code={callgraphMermaid(data.callgraph)} />
          })()}
        </div>
        {data.cfgFunctionsPath === activePath && (data.cfgFunctions.length > 0 || data.cfgError) && (
          <div className="border-t border-line px-2 py-1 text-[11px]">
            <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wide text-ink-muted">
              <span>control flow</span>
              <select
                className="ml-auto rounded border border-line bg-surface px-1 py-0.5 font-mono text-[10px] text-ink"
                value={data.cfgFn || ''}
                onChange={async (e) => {
                  const fn = e.target.value
                  if (!fn) { setData((d) => ({ ...d, cfgFn: '', cfg: undefined, cfgError: undefined })); return }
                  try {
                    const c = await call(`/sessions/${sessionId}/cfg?path=${encodeURIComponent(activePath)}&function=${encodeURIComponent(fn)}`)
                    setData((d) => ({ ...d, cfgFn: fn, cfg: c, cfgError: undefined }))
                  } catch (err) {
                    setData((d) => ({ ...d, cfgFn: fn, cfg: undefined, cfgError: String(err instanceof Error ? err.message : err) }))
                  }
                }}
              >
                <option value="">pick a function…</option>
                {data.cfgFunctions.map((fn) => <option key={fn} value={fn}>{fn}</option>)}
              </select>
            </div>
            {data.cfgError
              ? <div className="text-xs text-danger">{data.cfgError}</div>
              : data.cfg
                ? (
                  <div className="mt-1 max-h-[50vh] overflow-auto">
                    {(() => {
                      const dead = data.cfg.blocks.filter((b) => !b.reachable).length
                      return (
                        <>
                          <div className={dead > 0 ? 'text-xs text-danger' : 'text-xs text-ink-muted'}>
                            {dead > 0 ? `⚠ ${dead} unreachable block(s) — dead code` : 'all blocks reachable'}
                          </div>
                          <Mermaid code={cfgMermaid(data.cfg)} />
                        </>
                      )
                    })()}
                  </div>
                )
                : <div className="text-xs text-ink-muted">Green blocks are reachable; red blocks are dead code.</div>}
          </div>
        )}
        {data.trust && data.trustPath === activePath && (
          <div className="border-t border-line px-2 py-1 text-[11px]">
            <div className="font-mono text-[10px] uppercase tracking-wide text-ink-muted">test evidence</div>
            {data.trust.referencing_tests.length === 0
              ? <div className="text-xs text-danger">⚠ No tests reference this file — changes here are unverified.</div>
              : (
                <>
                  <div className="text-xs text-ink">{data.trust.referencing_tests.length} test file(s): {data.trust.referencing_tests.join(', ')}</div>
                  {data.trust.property_test_files.length > 0 && <div className="text-xs text-brand-300">includes property tests: {data.trust.property_test_files.join(', ')}</div>}
                  {data.trust.mutation && data.trust.mutation.total > 0 && (
                    <div className={data.trust.mutation.survived > 0 ? 'text-xs text-danger' : 'text-xs text-success'}>
                      mutation kill rate: {data.trust.mutation.killed}/{data.trust.mutation.total}
                      {data.trust.mutation.survived > 0 && ` — ${data.trust.mutation.survived} mutant(s) survived`}
                    </div>
                  )}
                </>
              )}
          </div>
        )}
      </div>
    ) : (
      <div className="rounded border border-line bg-surface">
        <div className="border-b border-line px-2 py-1 font-mono text-[10px] uppercase tracking-wide text-ink-muted">architecture map</div>
        <div className="max-h-[40vh] overflow-auto p-2">
          {data.archmap && data.archmap.nodes.length > 0
            ? <Mermaid code={callgraphMermaid(data.archmap)} />
            : <div className="text-xs text-ink-muted">No source files yet.</div>}
        </div>
        {onAsk && (
          <form
            className="flex gap-1 border-b border-line px-2 py-1"
            onSubmit={(e) => {
              e.preventDefault()
              const prompt = buildRepoQuestionPrompt(repoQuestion, data.structure, data.archmap)
              if (!prompt) return
              setRepoQuestion('')
              onAsk(prompt)
            }}
          >
            <input
              className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-0.5 text-xs text-ink"
              placeholder="ask about this project — answered with file+line citations…"
              value={repoQuestion}
              onChange={(e) => setRepoQuestion(e.target.value)}
            />
            <button className="rounded bg-brand-700 px-2 py-0.5 text-[10px] text-brand-fg" disabled={!sessionId}>ask</button>
          </form>
        )}
        <div className="border-b border-line px-2 py-1 font-mono text-[10px] uppercase tracking-wide text-ink-muted">project structure</div>
        <div className="max-h-[70vh] overflow-auto p-2 text-[11px]">
          {(() => {
            const rows = structureRows(data.structure)
            if (rows.length === 0) return <div className="text-xs text-ink-muted">No source files yet.</div>
            const byPath = new Map()
            for (const r of rows) {
              if (!byPath.has(r.path)) byPath.set(r.path, { lines: r.lines, symbols: [] })
              byPath.get(r.path).symbols.push(r)
            }
            return [...byPath.entries()].map(([p, { lines, symbols }]) => (
              <details key={p} className="mb-0.5">
                <summary className="cursor-pointer font-mono text-brand-300">{p} <span className="text-ink-muted">({lines} lines)</span></summary>
                <div className="pl-4">
                  {symbols.map((s, i) => (
                    <div key={i} className="font-mono text-ink-muted">
                      <span className={s.kind === 'class' ? 'text-accent' : ''}>{s.kind}</span> {s.name}
                    </div>
                  ))}
                </div>
              </details>
            ))
          })()}
        </div>
      </div>
    )
  } else if (tab === 'Diff') {
    const diffLines = (data.diff || '').split('\n')
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
    body = !data.diff ? (
      <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">
        No working-tree changes yet — edits the agent makes will appear here.
      </div>
    ) : (
      <div className="overflow-hidden rounded border border-line bg-surface">
        <div className="flex items-center gap-3 border-b border-line px-2 py-1 font-mono text-[10px]">
          <span className="text-success">+{added}</span>
          <span className="text-danger">-{removed}</span>
          <span className="ml-auto uppercase tracking-wide text-ink-muted">working tree</span>
        </div>
        {(data.diffSummary || []).length > 0 && (
          <div className="space-y-0.5 border-b border-line px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wide text-ink-muted">semantic changes</div>
            {data.diffSummary.filter((f) => f.summary).map((f) => (
              <div key={f.path} className="font-mono text-[10px]">
                <span className="text-brand-300">{f.path}</span>{' '}
                <span className="text-ink-muted">{f.summary}</span>
              </div>
            ))}
          </div>
        )}
        {impactMermaid(data.impact) && (
          <details className="border-b border-line px-2 py-1.5">
            <summary className="cursor-pointer text-[9px] uppercase tracking-wide text-ink-muted">impact graph</summary>
            <div className="pt-1">
              <Mermaid code={impactMermaid(data.impact)} />
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
  } else if (tab === 'Cost' && data.usage) {
    const u = data.usage
    body = (
      <div className="space-y-1">
        <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">requests</span><span className="text-ink">{u.requests ?? 0}</span></div>
        <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">input tokens</span><span className="text-ink">{u.input_tokens ?? 0}</span></div>
        <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">output tokens</span><span className="text-ink">{u.output_tokens ?? 0}</span></div>
        <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">cost (usd)</span><span className="text-brand-400">${(u.cost_usd ?? 0).toFixed(4)}</span></div>
        {(u.by_model || []).length > 0 && (
          <div className="mt-2">
            <div className="text-[10px] font-semibold uppercase text-ink-muted">by model</div>
            {(u.by_model || []).map((m) => (
              <div key={m.model} className="flex justify-between font-mono text-[10px] text-ink-muted">
                <span className="truncate">{m.model}</span>
                <span className="ml-2 shrink-0">{m.requests} req · {m.input_tokens}/{m.output_tokens} tok · ${(m.cost_usd ?? 0).toFixed(4)}</span>
              </div>
            ))}
          </div>
        )}
        {(u.by_request || []).length > 0 && (
          <div className="mt-2">
            <div className="text-[10px] font-semibold uppercase text-ink-muted">per request</div>
            {(u.by_request || []).map((r, i) => (
              <div key={i} className="flex justify-between font-mono text-[10px] text-ink-muted">
                <span className="truncate">{i + 1}. {r.model}</span>
                <span className="ml-2 shrink-0">{r.requests} req · {r.input_tokens}/{r.output_tokens} tok · ${(r.cost_usd ?? 0).toFixed(4)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  } else if (tab === 'Renders') {
    const renders = data.renders || []
    const renderStart = data.renderStart || 0
    const src = (r) => `/api/sessions/${sessionId}/render?path=${encodeURIComponent(r.path)}`
    const tile = (r, label) => (
      <a
        key={r.path}
        href={src(r)}
        target="_blank"
        rel="noreferrer"
        className="overflow-hidden rounded border border-line bg-surface hover:border-brand"
      >
        <img
          alt={r.name}
          loading="lazy"
          src={src(r)}
          className="h-24 w-full bg-canvas object-contain"
        />
        <div className="truncate px-1 py-0.5 font-mono text-[10px] text-ink-muted">
          {label ? `${label} · ` : ''}{r.path}
        </div>
      </a>
    )
    // Pair renders that differ only by theme or revision (R1): foo-dark.png /
    // foo-light.png and foo-before.png / foo-after.png show side-by-side.
    const PAIRS = [['dark', 'light'], ['before', 'after']]
    const paired = new Set()
    const pairGroups = []
    for (const r of renders) {
      if (paired.has(r.path)) continue
      const m = r.name.match(/^(.*?)[-_.](dark|light|before|after)\.[^.]+$/i)
      if (!m) continue
      for (const [a, b] of PAIRS) {
        if (m[2].toLowerCase() !== a) continue
        const sib = renders.find((x) => {
          if (paired.has(x.path)) return false
          const mm = x.name.match(/^(.*?)[-_.](dark|light|before|after)\.[^.]+$/i)
          return mm && mm[1].toLowerCase() === m[1].toLowerCase()
            && mm[2].toLowerCase() === b
        })
        if (!sib) continue
        paired.add(r.path)
        paired.add(sib.path)
        const label = (x) => x.name.match(/[-_.](dark|light|before|after)\./i)[1].toLowerCase()
        pairGroups.push({ base: m[1], left: r, right: sib, llabel: label(r), rlabel: label(sib) })
      }
    }
    const rest = renders.filter((r) => !paired.has(r.path))
    const group = (label, items) => (
      items.length === 0 ? null : (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wide text-ink-muted">{label}</div>
          <div className="grid grid-cols-2 gap-2">{items.map((r) => tile(r))}</div>
        </div>
      )
    )
    body = renders.length === 0 ? (
      <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">
        No images rendered in this workdir yet. Screenshots and previews appear here.
      </div>
    ) : (
      <div className="space-y-3">
        {pairGroups.length > 0 && (
          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-wide text-ink-muted">Comparisons</div>
            {pairGroups.map((g) => (
              <div key={g.base + g.left.path} className="rounded border border-line bg-surface p-1">
                <div className="px-1 pb-1 font-mono text-[10px] text-accent">{g.base}</div>
                <div className="grid grid-cols-2 gap-2">
                  {tile(g.left, g.llabel)}
                  {tile(g.right, g.rlabel)}
                </div>
              </div>
            ))}
          </div>
        )}
        {group('This session', rest.filter((r) => r.mtime >= renderStart))}
        {group('Earlier', rest.filter((r) => r.mtime < renderStart))}
      </div>
    )
  }

  return (
    <section className="flex shrink-0 flex-col overflow-hidden border-t border-neutral-800 bg-neutral-950" style={{ height }}>
      <div
        className="h-1 shrink-0 cursor-row-resize bg-neutral-800 transition-colors hover:bg-brand-600"
        onMouseDown={(e) => {
          e.preventDefault()
          const startY = e.clientY
          const startH = height
          document.body.style.userSelect = 'none'
          function onMove(ev) {
            // Drag up grows the dock.
            onResizeHeight(paneWidth('dock', startH, ev.clientY - startY))
          }
          function onUp() {
            window.removeEventListener('mousemove', onMove)
            window.removeEventListener('mouseup', onUp)
            document.body.style.userSelect = ''
          }
          window.addEventListener('mousemove', onMove)
          window.addEventListener('mouseup', onUp)
        }}
      />
      <div className="flex flex-wrap gap-1 border-b border-line px-2 py-1">
        {tabs.map((t) => (
          <button
            key={t}
            className={`relative rounded px-2 py-0.5 text-xs ${tab === t ? 'bg-surface text-brand' : 'text-ink-muted hover:text-ink'}`}
            onClick={() => setTab(t)}
          >
            {t}
            {t === 'Diff' && diffBadge && tab !== 'Diff' && (
              <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-brand-400" />
            )}
            {t === 'Artifacts' && artifactsPending > 0 && tab !== 'Artifacts' && (
              <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-warning" title={`${artifactsPending} artifact(s) waiting for you`} />
            )}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2 text-xs">{body}</div>
    </section>
  )
}

function Chat({ messages, streaming, onStop, onDecide, sessionId, suggestMode, onEditRevert, runId }) {
  const bottomRef = useRef(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
            <div
              className={`inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-base ${
                m.role === 'user' ? 'bg-brand-700 text-brand-fg' : 'bg-neutral-800 text-neutral-200'
              }`}
            >
              {m.role === 'user'
                ? m.text
                : <ReactMarkdown>{m.text}</ReactMarkdown>}
              {m.streaming && <span className="animate-pulse">▍</span>}
            </div>
            {m.toolEvents && <ToolTimeline events={m.toolEvents} />}
            {m.review && (
              <div className="my-1 rounded border border-accent/50 bg-accent/15 p-2 text-xs">
                <div className="font-semibold text-accent">Reviewer findings</div>
                <pre className="whitespace-pre-wrap text-neutral-300">{m.review}</pre>
              </div>
            )}
            {m.edits && suggestMode && m.edits.map((ed, ei) => (
              <EditBlock key={ei} edit={ed} sessionId={sessionId}
                onRevert={() => onEditRevert(i, ed)} />
            ))}
            {m.ask && runId && <AskUserCard ask={m.ask} runId={runId} />}
            {m.gate && !m.gate.startsWith('plan:') && <ApprovalCard command={m.gate} onDecide={onDecide} />}
            {m.gate && m.gate.startsWith('plan:') && sessionId && (
              <>
                <PlanCard sessionId={sessionId} onDecide={onDecide} />
                <div className="my-1 flex gap-2">
                  <button className="rounded bg-brand-700 px-3 py-1 text-xs text-brand-fg hover:bg-brand-600"
                    onClick={() => onDecide('approve')}>Approve plan</button>
                  <button className="rounded bg-danger px-3 py-1 text-xs text-danger-fg hover:bg-danger/90"
                    onClick={() => onDecide('deny')}>Reject</button>
                </div>
              </>
            )}
          </div>
        ))}
        {streaming && (
          <button
            className="rounded border border-danger/60 px-2 py-1 text-xs text-danger hover:bg-danger/20"
            onClick={onStop}
          >
            ■ Stop
          </button>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

function Prompt({ onSend, disabled, suggestMode, setSuggestMode, fixLoop, setFixLoop, models, model, setModel, yolo, setYolo, notify, toggleNotify }) {
  const [text, setText] = useState('')
  const [image, setImage] = useState(null) // {b64, name}
  const [checklists, setChecklists] = useState(null) // null = picker not opened yet
  const fileRef = useRef(null)
  // notify state is owned by App (single source of truth, L13) and passed in.

  // #93: checklist picker — load the list on first open, send a checklist run on pick.
  async function pickChecklist(name) {
    if (!name || disabled) return
    const md = await call(`/checklists/${name}`)
    onSend(checklistPrompt(name, md.markdown, ''))
  }

  return (
    <form
      className="flex flex-col gap-2 border-b border-neutral-800 p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (text.trim() || image) {
          onSend(text.trim() || 'describe this image', image)
          setText('')
          setImage(null)
        }
      }}
    >
      <div className="flex items-end gap-2">
        <textarea
          className="min-w-0 flex-1 resize-none rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              if (text.trim() || image) {
                onSend(text.trim() || 'describe this image', image)
                setText('')
                setImage(null)
              }
            }
          }}
          placeholder={disabled ? 'create or select a session first' : 'describe the task… (Enter to send, Shift+Enter for newline)'}
          disabled={disabled}
        />
        <button
          className="rounded bg-brand-700 px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand-600 disabled:opacity-40"
          disabled={disabled}
        >
          Send
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
      {image && (
        <div className="flex items-center gap-1 rounded bg-neutral-900 px-2 py-1 text-[10px] text-success">
          {image.name}
          <button type="button" aria-label="Remove image" className="text-danger" onClick={() => setImage(null)}>✕</button>
        </div>
      )}
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files && e.target.files[0]
          if (!f) return
          const reader = new FileReader()
          reader.onload = () => setImage({ b64: String(reader.result).split(',')[1], name: f.name })
          reader.readAsDataURL(f)
          e.target.value = ''
        }}
      />
      <button
        type="button"
        className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-400 hover:text-neutral-200 disabled:opacity-40"
        onClick={() => fileRef.current && fileRef.current.click()}
        disabled={disabled}
        title="attach image"
        aria-label="Attach image"
      >
        📎
      </button>
      <label className="flex items-center gap-1 text-[10px] text-neutral-400" title="agent edits become proposals you can revert">
        <input type="checkbox" checked={suggestMode} onChange={(e) => setSuggestMode(e.target.checked)} />
        suggest
      </label>
      <select
        className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
        value=""
        disabled={disabled}
        title="run a distilled review checklist against the project"
        aria-label="Checklist"
        onChange={async (e) => {
          const name = e.target.value
          e.target.value = ''
          if (!checklists) {
            const r = await call('/checklists')
            setChecklists(r.checklists)
          }
          pickChecklist(name)
        }}
        onFocus={async () => {
          if (!checklists) {
            const r = await call('/checklists')
            setChecklists(r.checklists)
          }
        }}
      >
        <option value="">checklist…</option>
        {(checklists || []).map((c) => (
          <option key={c.name} value={c.name}>{c.title || c.name}</option>
        ))}
      </select>
      <label className="flex items-center gap-1 text-[10px] text-neutral-400" title="run tests after the task and fix failures until green (max 3 rounds)">
        <input type="checkbox" checked={fixLoop} onChange={(e) => setFixLoop(e.target.checked)} />
        fix until green
      </label>
      {models && (
        <select
          className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          title={model && models.models[model] ? models.models[model] : 'configured default (main)'}
          aria-label="Model"
        >
          <option value="">default (main)</option>
          {['main', 'subagent', 'fallback', 'vision'].map((k) =>
            models.models[k] ? <option key={k} value={k}>{k} — {models.models[k]}</option> : null
          )}
        </select>
      )}
      <label className={`flex items-center gap-1 text-[10px] ${yolo ? 'text-danger' : 'text-neutral-400'}`} title="auto-approve every gated action for this session">
        <input type="checkbox" checked={yolo} onChange={(e) => setYolo(e.target.checked)} />
        yolo
      </label>
      <label
        className={`cursor-pointer text-sm ${notify ? '' : 'grayscale opacity-50'}`}
        title="notify when a run finishes or waits"
        aria-label="Toggle notifications"
        onClick={toggleNotify}
      >
        🔔
      </label>
      </div>
    </form>
  )
}

function AgentStrip({ status, quietSeconds, hasChanges, streaming, onReviewChanges }) {
  const stalled = streaming && quietSeconds >= 120
  return (
    <div className="flex h-7 shrink-0 items-center gap-3 border-b border-neutral-800 bg-neutral-950 px-3 text-[11px]">
      <span className={streaming ? 'text-brand-400' : 'text-neutral-500'}>
        <span
          className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${streaming ? 'animate-pulse bg-brand-400' : 'bg-neutral-600'}`}
        />
        agent {status || 'idle'}
      </span>
      {streaming && quietSeconds > 0 && (
        <span className={stalled ? 'text-red-400' : 'text-neutral-500'}>quiet {quietSeconds}s</span>
      )}
      {hasChanges && (
        <button
          className="ml-auto rounded bg-brand-700 px-2 py-0.5 text-[10px] font-medium text-white hover:bg-brand-600"
          onClick={onReviewChanges}
        >
          Review changes →
        </button>
      )}
    </div>
  )
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(null) // null = checking cookie
  const [workdir, setWorkdir] = useState(localStorage.getItem('codingdude-workdir') || '')
  const [sessions, setSessions] = useState([])
  const [projects, setProjects] = useState([])
  const [activeProject, setActiveProject] = useState(null)
  const [activeSession, setActiveSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [quietSeconds, setQuietSeconds] = useState(0) // seconds since last run event (watchdog)
  const [processes, setProcesses] = useState([]) // R31 #63: every spawned process, tracked until exit
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [diffBadge, setDiffBadge] = useState(false)
  // #189: pending choice/spec artifacts surface in the chat, not just the dock.
  const [artifactsAll, setArtifactsAll] = useState([])
  const [focusDiffTab, setFocusDiffTab] = useState(0)
  const [status, setStatus] = useState('idle')
  const [srv, setSrv] = useState(null)
  const [theme, setTheme] = useState(() =>
    localStorage.getItem('cd-theme') === 'light' ? 'light' : 'dark'
  )
  const [models, setModels] = useState(null)
  const [model, setModel] = useState(() => localStorage.getItem('cd-model') || '')
  const [yolo, setYolo] = useState(() => localStorage.getItem('cd-yolo') === '1')
  const [suggestMode, setSuggestMode] = useState(() => localStorage.getItem('cd-suggest') === '1')
  const [fixLoop, setFixLoop] = useState(false)
  const runRef = useRef(null)
  const esRef = useRef(null)
  const lastEventRef = useRef(Date.now()) // watchdog: last SSE event timestamp
  // R35 #72: shared file workspace — tree lives in the left rail, editor in main.
  const fileWs = useFileWorkspace(activeSession)

  // Resizable panes: widths persist across sessions.
  const [sidebarWidth, setSidebarWidth] = useState(
    () => parseInt(localStorage.getItem(PANE_SPECS.sidebar.key)) || PANE_SPECS.sidebar.fallback
  )
  const [rightWidth, setRightWidth] = useState(
    () => parseInt(localStorage.getItem(PANE_SPECS.right.key)) || PANE_SPECS.right.fallback
  )
  // R35 #74: Explorer rail is draggable like the other panes.
  const [railWidth, setRailWidth] = useState(
    () => parseInt(localStorage.getItem(PANE_SPECS.rail.key)) || PANE_SPECS.rail.fallback
  )
  // R35 #72: bottom dock height persists like the pane widths.
  const [dockHeight, setDockHeight] = useState(
    () => parseInt(localStorage.getItem(PANE_SPECS.dock.key)) || PANE_SPECS.dock.fallback
  )

  function dividerFor(which) {
    return (
      <div
        data-pane={which}
        className="w-1 shrink-0 cursor-col-resize bg-neutral-800 transition-colors hover:bg-brand-600"
        onMouseDown={(e) => {
          e.preventDefault()
          const startX = e.clientX
          const pane = PANE_SPECS[which]
          const startW = parseInt(localStorage.getItem(pane.key)) || pane.fallback
          const setW = { sidebar: setSidebarWidth, rail: setRailWidth, right: setRightWidth }[which]
          document.body.style.userSelect = 'none'
          function onMove(ev) {
            const w = paneWidth(which, startW, ev.clientX - startX)
            setW(w)
            localStorage.setItem(pane.key, String(w))
          }
          function onUp() {
            window.removeEventListener('mousemove', onMove)
            window.removeEventListener('mouseup', onUp)
            document.body.style.userSelect = ''
          }
          window.addEventListener('mousemove', onMove)
          window.addEventListener('mouseup', onUp)
        }}
      />
    )
  }


  // Any 401 tries a silent re-login first; only a failed grant shows the form.
  useEffect(() => {
    const onUnauthorized = async () => {
      if (!(await authLocal())) setLoggedIn(false)
    }
    window.addEventListener('cd-unauthorized', onUnauthorized)
    return () => window.removeEventListener('cd-unauthorized', onUnauthorized)
  }, [])

  // Backend build marker (version + boot time): fetched once logged in.
  useEffect(() => {
    if (!loggedIn) return
    call('/health').then(setSrv).catch(() => {})
  }, [loggedIn])

  // Theme: persist + apply to <html data-theme> so the token layer switches.
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('cd-theme', theme)
  }, [theme])

  // Model + YOLO: fetch the lineup once, persist the choice per browser.
  useEffect(() => {
    if (!loggedIn) return
    api.listModels().then(setModels).catch(() => {})
  }, [loggedIn])
  useEffect(() => { localStorage.setItem('cd-model', model) }, [model])
  useEffect(() => { localStorage.setItem('cd-yolo', yolo ? '1' : '0') }, [yolo])

  // Notifications: tab title + sound + toast on run state changes.
  const [notify, setNotify] = useState(() => localStorage.getItem('cd-notify') === '1')

  function toggleNotify() {
    const next = !notify
    setNotify(next)
    localStorage.setItem('cd-notify', next ? '1' : '0')
    if (next && 'Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }
  useEffect(() => {
    if (!status || status === 'idle') { document.title = 'CodingDude'; return }
    const map = {
      running: ['▶ CodingDude', false],
      finished: ['✓ CodingDude — done', true],
      stopped: ['■ CodingDude — stopped', true],
    }
    if (status.startsWith('waiting')) { map.waiting = ['⏸ CodingDude — approval needed', true] }
    if (status.startsWith('error')) { map.error = ['✗ CodingDude — error', true] }
    const entry = map[status] || ['CodingDude', false]
    document.title = entry[0]
    if (notify && entry[1] && 'Notification' in window && Notification.permission === 'granted') {
      try { new Notification(entry[0]) } catch { /* unavailable */ }
    }
    if (status !== 'running') {
      const audio = new Audio('data:audio/wav;base64,UklGRl9vT19XQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=')
      audio.volume = 0.3
      audio.play().catch(() => {})
    }
  }, [status, notify])

  // Transparent auth: valid cookie skips login; otherwise the local browser
  // gets one silently. The password form is only a fallback for old browsers.
  useEffect(() => {
    const boot = async () => {
      let ok = await checkAuth()
      if (!ok) ok = await authLocal()
      setLoggedIn(ok)
      // Session loading happens in ONE place: the projects effect below,
      // which reconciles the selected project and its sessions together.
    }
    boot()
  }, [])

  const refreshSessions = useCallback(async (wd) => {
    if (!wd) return
    try {
      const list = await api.listSessions(wd)
      setSessions(list)
      setError('')
      // Invariant (RC-4 fix): a selected session must belong to the selected
      // folder. Anything else auto-resumes this project's most recent session.
      setActiveSession((cur) => {
        if (cur && list.some((s) => s.session_id === cur)) return cur
        return list[0]?.session_id || null
      })
    } catch (e) {
      setError(String(e.message))
    }
  }, [])

  useEffect(() => {
    if (loggedIn) {
      api.listProjects().then((list) => {
        setProjects(list)
        // Restore the saved project by id, else the most recently active one
        // (the backend returns projects recent-first).
        const saved = localStorage.getItem('cd-project-id')
        const match = list.find((x) => x.id === Number(saved)) || list[0]
        if (match) {
          setActiveProject(match)
          setWorkdir(match.workdir)
          refreshSessions(match.workdir)
        }
      }).catch(() => {})
    }
  }, [loggedIn, refreshSessions])

  // Persist the selection so the next startup resumes exactly where you
  // stopped — previously codingdude-workdir was only saved on newSession(),
  // and cd-project-id was read but never written.
  useEffect(() => {
    if (activeProject) localStorage.setItem('cd-project-id', String(activeProject.id))
  }, [activeProject])
  useEffect(() => {
    if (workdir) localStorage.setItem('codingdude-workdir', workdir)
  }, [workdir])

  // Auto-resume: loading a session's history follows the selection itself.
  useEffect(() => {
    if (!loggedIn || !activeSession) return
    loadMessages(activeSession).catch((e) => setError(String(e.message)))
  }, [activeSession, loggedIn])

  const [runningSessions, setRunningSessions] = useState(() => new Map()) // session_id -> run_id
  const attachedRunRef = useRef(null)
  // Set once this browser has seen a terminal event for a run — an SSE error
  // afterwards (stream end after terminal, channel reaped) must settle
  // silently, never surface "lost connection" (post-reaper bouncing popups).
  const terminalSeenRef = useRef(null)
  useEffect(() => {
    if (!loggedIn) return
    let stop = false
    async function poll() {
      try {
        const active = await api.activeRuns()
        if (!stop) setRunningSessions(new Map(active.map((r) => [r.session_id, r.run_id])))
      } catch { /* transient */ }
      if (!stop) setTimeout(poll, 5000)
    }
    poll()
    return () => { stop = true }
  }, [loggedIn])

  // R29 (#58): on boot/refresh, a run that is still live in the selected
  // session must reattach — reload the persisted exchange, then stream the
  // tail from the run's (buffered) SSE channel.
  // #147: after a refresh, a run that is still waiting on the user must
  // re-show the pending ask/gate card — the interaction is persisted in the
  // session trace (ASK_USER/GATE_REQUEST + RESOLVED markers).
  async function restorePending(sessionId, runId) {
    try {
      const tr = await call(`/sessions/${sessionId}/trace?limit=300`)
      const p = pickPending(tr || [], runId)
      if (!p) return
      setMessages((msgs) => {
        if (!msgs.length) return msgs
        const copy = [...msgs]
        const last = { ...copy[copy.length - 1] }
        if (p.kind === 'ask') last.ask = { questions: p.questions, answered: false }
        else last.gate = p.command
        copy[copy.length - 1] = last
        return copy
      })
      if (p.kind === 'gate') setStatus('waiting for approval')
    } catch { /* transient; the trace poll will retry */ }
  }

  useEffect(() => {
    const runId = runToReattach(runningSessions, activeSession, attachedRunRef.current)
    if (!runId) return
    setStreaming(true)
    lastEventRef.current = Date.now()
    setStatus('running')
    runRef.current = runId
    loadMessages(activeSession).catch(() => {})
    restorePending(activeSession, runId)
    attach(runId)
  }, [activeSession, runningSessions])

  async function loadMessages(sessionId) {
    let raw
    try {
      raw = await api.getMessages(sessionId)
    } catch {
      return // transient server hiccup; the trace poll will retry
    }
    // Rebuild the timeline from stored messages, including tool calls, so a
    // resumed session shows what happened instead of just prose (L11).
    const turns = []
    let pendingTools = []
    const flush = (text) => {
      turns.push({ role: 'assistant', text, toolEvents: pendingTools })
      pendingTools = []
    }
    for (const m of raw) {
      for (const p of m.parts || []) {
        if (p.part_kind === 'user-prompt') {
          if (pendingTools.length) flush('')
          turns.push({ role: 'user', text: p.content })
        } else if (p.part_kind === 'tool-call') {
          pendingTools.push({ tool_name: p.tool_name })
        } else if (p.part_kind === 'tool-return') {
          const t = pendingTools.find(
            (x) => x.tool_name === p.tool_name && x.result === undefined
          )
          if (t) t.result = typeof p.content === 'string' ? p.content : JSON.stringify(p.content)
        } else if (p.part_kind === 'text' && m.kind === 'response') {
          flush(p.content)
        }
      }
    }
    if (pendingTools.length) flush('')
    setMessages(turns)
  }

  function newSession() {
    if (!workdir) return
    api
      .createSession(workdir)
      .then((r) => {
        setActiveSession(r.session_id)
        setMessages([])
        refreshSessions(workdir)
      })
      .catch((e) => setError(String(e.message)))
  }

  function send(prompt, image) {
    if (!activeSession || streaming) return
    // Invariant guard (RC-4): never send into a session that isn't in the
    // selected project's session list (wrong-folder execution).
    if (!sessions.some((s) => s.session_id === activeSession)) {
      setError('active session does not belong to the selected project — pick or create a session here')
      return
    }
    setMessages((m) => [
      ...m,
      { role: 'user', text: prompt },
      { role: 'assistant', text: '', streaming: true, toolEvents: [] },
    ])
    setStreaming(true)
    lastEventRef.current = Date.now()
    setStatus('running')
    setError('')
    api
      .startRun(
        activeSession,
        prompt,
        model && models ? models.models[model] : null,
        fixLoop,
        image ? image.b64 : null,
        yolo,
      )
      .then(({ run_id }) => {
        runRef.current = run_id
        attach(run_id)
      })
      .catch((e) => {
        setStreaming(false)
        setError(String(e.message))
      })
  }

  // R31 #63: track every process the session spawned (server DB is the
  // source of truth) until it exits — visible even when a run wedges.
  useEffect(() => {
    if (!activeSession) {
      setProcesses([])
      return
    }
    let alive = true
    const load = () =>
      call(`/sessions/${activeSession}/processes`)
        .then((rows) => {
          if (alive) setProcesses((prev) => mergeProcesses(prev, rows || []))
        })
        .catch(() => {}) // transient; next poll retries
    load()
    const t = setInterval(load, 3000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [activeSession])

  // #189: poll artifacts for the active session so pending cards surface in
  // the chat (the run SSE has no artifact event; the Artifacts tab alone hid them).
  useEffect(() => {
    if (!activeSession) {
      setArtifactsAll([])
      return
    }
    let alive = true
    const load = () =>
      call(`/sessions/${activeSession}/artifacts`)
        .then((rows) => { if (alive) setArtifactsAll(rows || []) })
        .catch(() => {}) // transient; next poll retries
    load()
    const t = setInterval(load, 3000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [activeSession])
  const pending = pendingArtifacts(artifactsAll)

  // Watchdog (R2): a live run that emits nothing for a while must not look
  // dead — surface "still working…" with the quiet duration.
  useEffect(() => {
    if (!streaming) {
      setQuietSeconds(0)
      return
    }
    const t = setInterval(() => {
      setQuietSeconds(Math.floor((Date.now() - lastEventRef.current) / 1000))
    }, 1000)
    return () => clearInterval(t)
  }, [streaming])

  function attach(run_id, attempt = 0) {
    // (R2) SSE errors used to silently fake a finished run — the "agent hung"
    // report. Instead: reattach with backoff while the run is alive, and only
    // conclude the run ended once the server says the worker is gone.
    const es = new EventSource(api.eventStreamUrl(run_id))
    esRef.current = es
    attachedRunRef.current = run_id
    es.onmessage = (e) => {
      lastEventRef.current = Date.now()
      let ev
      try {
        ev = JSON.parse(e.data)
      } catch (err) {
        console.warn('skipping malformed SSE data', e.data)
        return
      }
      if (['RUN_FINISHED', 'RUN_ERROR', 'RUN_CANCELLED'].includes(ev.type)) {
        terminalSeenRef.current = run_id
      }
      setMessages((msgs) => {
            const copy = [...msgs]
            const last = { ...copy[copy.length - 1] }
            if (ev.type === 'TEXT_MESSAGE_CONTENT') last.text += ev.delta
            if (ev.type === 'TOOL_CALL_START') {
              // Remember each in-flight tool's args so a pending gate can be
              // matched to ITS tool's completion (parallel tool calls mean a
              // sibling's END must not clear the gate card).
              last.inFlight = { ...(last.inFlight || {}), [ev.tool_name]: ev.args || '' }
            }
            if (ev.type === 'TOOL_CALL_END') {
              last.toolEvents = [...(last.toolEvents || []), { tool_name: ev.tool_name, result: ev.result }]
              // Clear the gate only when the gated command itself completed —
              // not when a sibling tool finished while the gate was pending.
              let startedCmd = (last.inFlight || {})[ev.tool_name] || ''
              try { startedCmd = JSON.parse(startedCmd).command || startedCmd } catch {}
              if (
                last.gate && startedCmd &&
                (startedCmd === last.gate || startedCmd.includes(last.gate) || last.gate.includes(startedCmd))
              ) last.gate = null
              if (ev.tool_name === 'edit_file' || ev.tool_name === 'write_file') setDiffBadge(true)
            }
            if (ev.type === 'EDIT_APPLIED') {
              last.edits = [...(last.edits || []), { path: ev.path, before: ev.before, after: ev.after }]
            }
            if (ev.type === 'GATE_REQUEST') {
              last.gate = ev.command
              setStatus('waiting for approval')
            }
            if (ev.type === 'ASK_USER') {
              last.ask = { questions: ev.questions || [], answered: false }
            }
            if (ev.type === 'REVIEW_FINDINGS') last.review = ev.findings
            if (['RUN_FINISHED', 'RUN_ERROR', 'RUN_CANCELLED'].includes(ev.type)) {
              last.streaming = false
              // #145: pending ask/gate cards must not outlive the run —
              // the worker is gone, answering would just 404.
              last.ask = null
              last.gate = null
              setStatus(ev.type === 'RUN_ERROR' ? `error: ${ev.message || ''}` : 'finished')
              if (ev.type === 'RUN_ERROR') setError(ev.message || 'run error')
              es.close()
              attachedRunRef.current = null
              setStreaming(false)
              loadMessages(activeSession)
            }
            copy[copy.length - 1] = last
            return copy
      })
    }
    es.onerror = () => {
      es.close()
      // Stream ended after we already saw the terminal (server closes the
      // SSE stream right after RUN_FINISHED; browser auto-reconnect races
      // channel reaping): settle silently — the run IS finished.
      if (terminalSeenRef.current === run_id) {
        attachedRunRef.current = null
        setStreaming(false)
        return
      }
      if (attempt >= SSE_MAX_RETRIES) {
        // Server unreachable for the whole retry budget (#78): the worker may
        // still have completed and persisted the run — reload the persisted
        // exchange before declaring the connection lost, so the UI settles on
        // the real outcome instead of a dangling spinner.
        attachedRunRef.current = null
        setStreaming(false)
        setStatus('error')
        setError('lost connection to the run — reload the session to see its persisted output')
        setMessages((msgs) => {
          const copy = [...msgs]
          copy[copy.length - 1] = { ...copy[copy.length - 1], streaming: false }
          return copy
        })
        loadMessages(activeSession)
        return
      }
      setStatus('connection lost — reconnecting…')
      setTimeout(() => {
        call(`/runs/${run_id}/alive`)
          .then(({ alive }) => {
            if (alive) {
              attach(run_id, attempt + 1)
            } else {
              // Worker already gone (run finished while we were detached):
              // reload the persisted exchange and finish cleanly.
              attachedRunRef.current = null
              setStreaming(false)
              setStatus('finished')
              setMessages((msgs) => {
                const copy = [...msgs]
                copy[copy.length - 1] = { ...copy[copy.length - 1], streaming: false }
                return copy
              })
              loadMessages(activeSession)
            }
          })
          .catch(() => attach(run_id, attempt + 1))
      }, sseRetryDelayMs(attempt))
    }
  }

  function onEditRevert(msgIndex, edit) {
    setMessages((msgs) => msgs.map((m, idx) => {
      if (idx !== msgIndex || !m.edits) return m
      return { ...m, edits: m.edits.filter((x) => x !== edit) }
    }))
  }

  function stop() {
    if (runRef.current) api.cancelRun(runRef.current).catch(() => {})
    esRef.current?.close()
    attachedRunRef.current = null
    runRef.current = null // #145: kills any zombie AskUserCard rendering
    setMessages((msgs) => clearPendingPrompts(msgs))
    setStreaming(false)
    setStatus('stopped')
  }

  function decide(decision) {
    setMessages((msgs) => {
      const copy = [...msgs]
      const last = { ...copy[copy.length - 1] }
      last.gate = null
      copy[copy.length - 1] = last
      return copy
    })
    setStatus('running')
    if (runRef.current) api.approve(runRef.current, decision).catch((e) => setError(String(e.message)))
  }

  if (loggedIn === null) {
    return <div className="flex h-screen items-center justify-center bg-neutral-900 text-neutral-500">connecting…</div>
  }

  if (!loggedIn) {
    return (
      <Login
        onLoggedIn={() => {
          setLoggedIn(true)
          setError('')
          refreshSessions(workdir)
        }}
      />
    )
  }

  return (
    <div className="flex h-screen flex-col bg-neutral-900 text-neutral-200">
      <div className="flex min-h-0 flex-1">
        {dividerFor('sidebar')}
        <Sidebar
          width={sidebarWidth}
          projects={projects}
          activeProject={activeProject}
          onSelectProject={(p) => {
            setActiveProject(p)
            setWorkdir(p.workdir)
            setActiveSession(null)
            setMessages([])
            refreshSessions(p.workdir)
          }}
          onAddProject={(name, wd) => {
            api.addProject(name, wd)
              .then((proj) => {
                setProjects((list) => [...list, proj].sort((a, b) => a.name.localeCompare(b.name)))
                setActiveProject(proj)
                setWorkdir(proj.workdir)
                setActiveSession(null)
                setMessages([])
              })
              .catch((e) => setError(String(e.message)))
          }}
          onDeleteProject={(id) => {
            api.deleteProject(id).catch(() => {})
            setProjects((list) => list.filter((x) => x.id !== id))
            if (activeProject?.id === id) setActiveProject(null)
          }}
          workdir={workdir}
          setWorkdir={setWorkdir}
          sessions={sessions}
          activeSession={activeSession}
          runningSessions={new Set(runningSessions.keys())}
          onSelect={(id) => {
            setActiveSession(id)  // history loads via the activeSession effect
          }}
          onNewSession={newSession}
        />
        <nav className="flex shrink-0 flex-col border-r border-neutral-800 bg-neutral-950" style={{ width: railWidth }}>
          <div className="px-2 py-1 text-[10px] uppercase tracking-wide text-ink-muted">Explorer</div>
          <FileTree sessionId={activeSession} onOpen={(p) => fileWs.openFile(p)} />
        </nav>
        {dividerFor('rail')}
        <main className="flex min-w-0 flex-1 flex-col">
          {error && <div className="bg-danger/15 px-4 py-1 text-xs text-danger">{error}</div>}
          <AgentStrip
            status={streaming ? status : 'idle'}
            quietSeconds={quietSeconds}
            hasChanges={diffBadge}
            streaming={streaming}
            onReviewChanges={() => setFocusDiffTab((n) => n + 1)}
          />
          <EditorPane ws={fileWs} onAsk={send} />
        </main>
        {dividerFor('right')}
        <aside
          className="flex min-w-0 shrink-0 flex-col overflow-hidden border-l border-neutral-800 bg-neutral-950"
          style={{ width: rightWidth }}
        >
          <Prompt
            onSend={send}
            disabled={!activeSession || streaming}
            suggestMode={suggestMode}
            setSuggestMode={(v) => { setSuggestMode(v); localStorage.setItem('cd-suggest', v ? '1' : '0') }}
            fixLoop={fixLoop}
            setFixLoop={setFixLoop}
            models={models}
            model={model}
            setModel={setModel}
            yolo={yolo}
            setYolo={setYolo}
            notify={notify}
            toggleNotify={toggleNotify}
          />
          <PendingArtifactCard
            items={pending}
            onResponded={() => {
              call(`/sessions/${activeSession}/artifacts`).then(setArtifactsAll).catch(() => {})
            }}
          />
          <Chat messages={messages} streaming={streaming} onStop={stop} onDecide={decide} sessionId={activeSession} suggestMode={suggestMode} onEditRevert={onEditRevert} runId={runRef.current} />
        </aside>
      </div>
      <DockPanel
        sessionId={activeSession}
        refreshKey={refreshKey}
        diffBadge={diffBadge}
        artifactsPending={pending.length}
        workdir={workdir}
        processes={processes}
        height={dockHeight}
        focusDiff={focusDiffTab}
        activePath={fileWs.active?.path || ''}
        onAsk={send}
        onResizeHeight={(h) => { setDockHeight(h); localStorage.setItem('cd-dock-h', String(h)) }}
      />
      <footer className="flex items-center justify-between border-t border-neutral-800 bg-neutral-950 px-3 py-1 text-[10px] text-neutral-500">
        <span>
          {activeSession ? `session ${activeSession.slice(0, 8)}` : 'no session'} ·{' '}
          {sessions.find((s) => s.session_id === activeSession)?.workdir || workdir || 'no workdir'}
          {activeSession && !sessions.some((s) => s.session_id === activeSession) && (
            <span className="text-danger"> · ⚠ session not in selected project</span>
          )}
        </span>
        <span className="text-neutral-600" title="frontend build · backend server build">
          ui v{UI_VERSION}{UI_SHA ? `+${UI_SHA}` : ''} {shortStamp(UI_BUILD)} · srv v{srv?.version ?? '?'}{srv?.git_sha ? `+${srv.git_sha}` : ''} {shortStamp(srv?.started_at)}
        </span>
        <button
          className="rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-400 hover:text-neutral-200"
          title="toggle light / dark"
          onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
        >
          {theme === 'dark' ? 'dark' : 'light'}
        </button>
        {processes.length > 0 && (
          <span
            className="ml-2 cursor-help text-neutral-500"
            title={processes.map(describeProcess).join('\n')}
          >
            ⚙ {processes.filter((p) => p.status === 'running').length} live / {processes.length} spawned
          </span>
        )}
      </footer>
    </div>
  )
}

