import React, { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import CodeEditor from './CodeEditor.jsx'
import { api, authLocal, call, checkAuth, login } from './api'

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
        <h1 className="mb-4 text-center text-lg font-bold text-brand-400">CodingDude</h1>
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
      <h1 className="text-lg font-bold text-brand-400">CodingDude</h1>
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
              {e.result && <pre className="whitespace-pre-wrap text-ink-muted">{e.result}</pre>}
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
  const [answers, setAnswers] = useState({})
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  if (!ask || !ask.questions || !ask.questions.length) return null
  if (sent) return null
  const submit = () => {
    if (sending) return
    setSending(true)
    setError('')
    const out = {}
    for (const q of ask.questions || []) {
      out[q.question] = answers[q.question] ?? ''
    }
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
        {(ask.questions || []).map((q) => (
          <div key={q.question}>
            <div className="mb-1 text-xs text-ink">{q.question}</div>
            {(q.options || []).length > 0 ? (
              <div className="space-y-1">
                {(q.options || []).map((o) => (
                  <label key={o} className="flex items-center gap-2 text-xs text-ink-muted">
                    <input
                      type={q.multi ? 'checkbox' : 'radio'}
                      name={q.question}
                      checked={q.multi
                        ? (answers[q.question] || []).includes(o)
                        : answers[q.question] === o}
                      onChange={() => setAnswers((a) => {
                        const cur = a[q.question]
                        if (q.multi) {
                          const list = Array.isArray(cur) ? cur : []
                          return { ...a, [q.question]: list.includes(o)
                            ? list.filter((x) => x !== o) : [...list, o] }
                        }
                        return { ...a, [q.question]: o }
                      })}
                    />
                    {o}
                  </label>
                ))}
              </div>
            ) : (
              <input
                className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
                value={answers[q.question] || ''}
                onChange={(e) => setAnswers((a) => ({ ...a, [q.question]: e.target.value }))}
              />
            )}
          </div>
        ))}
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

function FileExplorer({ sessionId }) {
  const [tree, setTree] = useState(null)
  const [openPath, setOpenPath] = useState(null)
  const [file, setFile] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saved, setSaved] = useState(false)

  async function refresh() {
    setTree(await call(`/sessions/${sessionId}/tree`))
  }
  useEffect(() => {
    if (sessionId) refresh().catch(() => {})
  }, [sessionId])

  async function openFile(path) {
    try {
      const f = await call(`/sessions/${sessionId}/file?path=${encodeURIComponent(path)}`)
      setFile(f)
      setOpenPath(path)
      setEditing(false)
      setSaved(false)
    } catch (e) {
      setFile({ path, content: `cannot open: ${e.message}`, is_markdown: false })
      setOpenPath(path)
      setEditing(false)
    }
  }

  async function save() {
    await call(`/sessions/${sessionId}/file`, {
      method: 'PUT',
      body: JSON.stringify({ path: openPath, content: draft }),
    })
    setSaved(true)
    setEditing(false)
    const f = await call(`/sessions/${sessionId}/file?path=${encodeURIComponent(openPath)}`)
    setFile(f)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="max-h-48 overflow-y-auto rounded bg-neutral-900 p-1">
        {tree ? tree.children.map((c) => (
          <TreeNode key={c.path} node={c} depth={0} onOpen={openFile} />
        )) : <div className="text-neutral-600">loading…</div>}
      </div>
      {openPath && (
        <div className="flex min-h-0 flex-1 flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="truncate font-mono text-[10px] text-brand-300">{openPath}</span>
            <div className="flex gap-1">
              <button
                className="rounded bg-neutral-700 px-2 py-0.5 text-[10px] text-ink"
                onClick={() => {
                  if (!editing) setDraft(file?.content || '')
                  setEditing(!editing)
                }}
              >{editing ? 'view' : 'edit'}</button>
              {editing && (
                <button
                  className="rounded bg-brand-700 px-2 py-0.5 text-[10px] text-brand-fg"
                  onClick={save}
                >save</button>
              )}
            </div>
          </div>
          {saved && <div className="text-[10px] text-brand-400">saved ✓</div>}
          {editing ? (
            <div className="min-h-0 flex-1 overflow-hidden rounded border border-neutral-700">
              <CodeEditor path={openPath} value={draft} onChange={setDraft} height="100%" />
            </div>
          ) : file?.is_markdown ? (
            <div className="min-h-0 flex-1 overflow-y-auto rounded bg-neutral-900 p-2 text-xs text-neutral-200">
              <ReactMarkdown>{file.content}</ReactMarkdown>
            </div>
          ) : (
            <pre className="min-h-0 flex-1 overflow-auto rounded bg-neutral-900 p-2 font-mono text-[11px] text-neutral-300">
              {file?.content}
            </pre>
          )}
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

function Planning({ workdir }) {
  const [data, setData] = useState(null)
  const [newTitle, setNewTitle] = useState('')
  const [kind, setKind] = useState('ticket')

  async function refresh() {
    if (!workdir) return
    try { setData(await api.getPlanning(workdir)) } catch { /* transient */ }
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
      : kind === 'roadmap' ? api.addRoadmapItem : api.addDecision
    await fn(workdir, title, '').catch(() => {})
    setNewTitle('')
    refresh()
  }

  if (!workdir) {
    return <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">Select a project first.</div>
  }
  if (!data) {
    return <div className="text-ink-muted">loading…</div>
  }
  const statusColor = (s) => s === 'done' ? 'text-success'
    : s === 'in_progress' ? 'text-warning' : 'text-ink-muted'
  return (
    <div className="space-y-3">
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

function RightPanel({ sessionId, refreshKey, diffBadge, tabRef, width, workdir }) {
  const tabs = ['Diff', 'Planning', 'Renders', 'Files', 'Terminal', 'Trace', 'Cost', 'Memory', 'MCP', 'Standards']
  const [tab, setTab] = useState('Diff')
  const [data, setData] = useState({})

  useEffect(() => {
    if (!sessionId || tab === 'Files' || tab === 'Standards' || tab === 'Terminal' || tab === 'Planning') return
    let stop = false
    async function poll() {
      try {
        if (tab === 'Diff') { const r = await call(`/sessions/${sessionId}/diff`); setData((d) => ({ ...d, diff: r.diff })) }
        if (tab === 'Cost') { const u = await call(`/sessions/${sessionId}/usage`); setData((d) => ({ ...d, usage: u })) }
        if (tab === 'Memory') { const m = await call('/memory'); setData((d) => ({ ...d, memory: m })) }
        if (tab === 'MCP') { const m = await api.listMcp(sessionId); setData((d) => ({ ...d, mcp: m })) }
        if (tab === 'Trace') {
          const tr = await call(`/sessions/${sessionId}/trace?limit=50`)
          const cps = await call(`/sessions/${sessionId}/checkpoints`)
          setData((d) => ({ ...d, trace: tr, checkpoints: cps }))
        }
        if (tab === 'Renders') {
          const r = await call(`/sessions/${sessionId}/renders`)
          setData((d) => ({ ...d, renders: r.renders, renderStart: r.session_start }))
        }
      } catch { /* transient */ }
      if (!stop) setTimeout(poll, 4000)
    }
    poll()
    return () => { stop = true }
  }, [sessionId, tab])

  async function toggleServer(name, disabled) {
    await api.toggleMcp(sessionId, name, disabled).catch(() => {})
    const m = await api.listMcp(sessionId)
    setData((d) => ({ ...d, mcp: m }))
  }

  const [review, setReview] = useState(null) // {findings} | 'running'
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
    await fetch(`/api/skills/detail/${encodeURIComponent(name)}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${localStorage.getItem('codingdude-token') || ''}` },
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
  } else if (tab === 'Planning') {
    body = <Planning workdir={workdir} />
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
        <div className="max-h-[70vh] overflow-auto p-2 font-mono text-[11px] leading-[1.5]">
          {diffLines.map((l, i) => (
            <div key={i} className={`whitespace-pre ${lineClass(l)}`}>{l || ' '}</div>
          ))}
        </div>
      </div>
    )
  } else if (tab === 'Files') {
    body = <FileExplorer sessionId={sessionId} />
  } else if (tab === 'Cost' && data.usage) {
    const u = data.usage
    body = (
      <div className="space-y-1">
        <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">requests</span><span className="text-ink">{u.requests ?? 0}</span></div>
        <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">input tokens</span><span className="text-ink">{u.input_tokens ?? 0}</span></div>
        <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">output tokens</span><span className="text-ink">{u.output_tokens ?? 0}</span></div>
        <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">cost (usd)</span><span className="text-brand-400">${(u.cost_usd ?? 0).toFixed(4)}</span></div>
      </div>
    )
  } else if (tab === 'Renders') {
    const renders = data.renders || []
    const renderStart = data.renderStart || 0
    const tile = (r) => (
      <a
        key={r.path}
        href={`/api/sessions/${sessionId}/render?path=${encodeURIComponent(r.path)}`}
        target="_blank"
        rel="noreferrer"
        className="overflow-hidden rounded border border-line bg-surface hover:border-brand"
      >
        <img
          alt={r.name}
          loading="lazy"
          src={`/api/sessions/${sessionId}/render?path=${encodeURIComponent(r.path)}`}
          className="h-24 w-full bg-canvas object-contain"
        />
        <div className="truncate px-1 py-0.5 font-mono text-[10px] text-ink-muted">{r.path}</div>
      </a>
    )
    const group = (label, items) => (
      items.length === 0 ? null : (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wide text-ink-muted">{label}</div>
          <div className="grid grid-cols-2 gap-2">{items.map(tile)}</div>
        </div>
      )
    )
    body = renders.length === 0 ? (
      <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">
        No images rendered in this workdir yet. Screenshots and previews appear here.
      </div>
    ) : (
      <div className="space-y-3">
        {group('This session', renders.filter((r) => r.mtime >= renderStart))}
        {group('Earlier', renders.filter((r) => r.mtime < renderStart))}
      </div>
    )
  }

  return (
    <aside className="flex shrink-0 flex-col overflow-hidden border-l border-neutral-800 bg-neutral-950 p-3" style={{ width }}>
      <div className="mb-2 flex flex-wrap gap-1 border-b border-line pb-2">
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
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto text-xs">{body}</div>
    </aside>
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

function Prompt({ onSend, disabled, suggestMode, setSuggestMode, fixLoop, setFixLoop, models, model, setModel, yolo, setYolo }) {
  const [text, setText] = useState('')
  const [image, setImage] = useState(null) // {b64, name}
  const fileRef = useRef(null)
  const [notify, setNotify] = useState(() => localStorage.getItem('cd-notify') === '1')

  function toggleNotify() {
    const next = !notify
    setNotify(next)
    localStorage.setItem('cd-notify', next ? '1' : '0')
    if (next && 'Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }

  return (
    <form
      className="flex flex-wrap items-center gap-2 border-b border-neutral-800 p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (text.trim() || image) {
          onSend(text.trim() || 'describe this image', image)
          setText('')
          setImage(null)
        }
      }}
    >
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
      <button
        className="rounded bg-brand-700 px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand-600 disabled:opacity-40"
        disabled={disabled}
      >
        Send
      </button>
    </form>
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
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [diffBadge, setDiffBadge] = useState(false)
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

  // Resizable panes: widths persist across sessions.
  const [sidebarWidth, setSidebarWidth] = useState(
    () => Math.min(500, Math.max(180, parseInt(localStorage.getItem('cd-sidebar-w')) || 256))
  )
  const [rightWidth, setRightWidth] = useState(
    () => Math.min(700, Math.max(280, parseInt(localStorage.getItem('cd-right-w')) || 384))
  )

  function dividerFor(which) {
    return (
      <div
        data-pane={which}
        className="w-1 shrink-0 cursor-col-resize bg-neutral-800 transition-colors hover:bg-brand-600"
        onMouseDown={(e) => {
          e.preventDefault()
          const startX = e.clientX
          const startW = which === 'sidebar' ? sidebarWidth : rightWidth
          document.body.style.userSelect = 'none'
          function onMove(ev) {
            if (which === 'sidebar') {
              const w = Math.min(500, Math.max(180, startW + ev.clientX - startX))
              setSidebarWidth(w)
              localStorage.setItem('cd-sidebar-w', String(w))
            } else {
              const w = Math.min(700, Math.max(280, startW - (ev.clientX - startX)))
              setRightWidth(w)
              localStorage.setItem('cd-right-w', String(w))
            }
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

  const [runningSessions, setRunningSessions] = useState(() => new Set())
  useEffect(() => {
    if (!loggedIn) return
    let stop = false
    async function poll() {
      try {
        const active = await api.activeRuns()
        if (!stop) setRunningSessions(new Set(active.map((r) => r.session_id)))
      } catch { /* transient */ }
      if (!stop) setTimeout(poll, 5000)
    }
    poll()
    return () => { stop = true }
  }, [loggedIn])

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
        const es = new EventSource(api.eventStreamUrl(run_id))
        esRef.current = es
        es.onmessage = (e) => {
          let ev
          try {
            ev = JSON.parse(e.data)
          } catch (err) {
            console.warn('skipping malformed SSE data', e.data)
            return
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
              setStatus(ev.type === 'RUN_ERROR' ? `error: ${ev.message || ''}` : 'finished')
              if (ev.type === 'RUN_ERROR') setError(ev.message || 'run error')
              es.close()
              setStreaming(false)
              loadMessages(activeSession)
            }
            copy[copy.length - 1] = last
            return copy
          })
        }
        es.onerror = () => {
          es.close()
          setStreaming(false)
          setMessages((msgs) => {
            const copy = [...msgs]
            copy[copy.length - 1] = { ...copy[copy.length - 1], streaming: false }
            return copy
          })
          loadMessages(activeSession)
        }
      })
      .catch((e) => {
        setStreaming(false)
        setError(String(e.message))
      })
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
          runningSessions={runningSessions}
          onSelect={(id) => {
            setActiveSession(id)  // history loads via the activeSession effect
          }}
          onNewSession={newSession}
        />
        <main className="flex min-w-0 flex-1 flex-col">
          {error && <div className="bg-danger/15 px-4 py-1 text-xs text-danger">{error}</div>}
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
          />
          <Chat messages={messages} streaming={streaming} onStop={stop} onDecide={decide} sessionId={activeSession} suggestMode={suggestMode} onEditRevert={onEditRevert} runId={runRef.current} />
        </main>
        {dividerFor('right')}
        <RightPanel
          width={rightWidth}
          sessionId={activeSession}
          refreshKey={refreshKey}
          diffBadge={diffBadge}
          workdir={workdir}
        />
      </div>
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
        <span className={streaming ? 'text-brand-400' : ''}>{status}</span>
      </footer>
    </div>
  )
}
