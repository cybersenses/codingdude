import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, call, checkAuth, login } from './api.js'

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
          <div className="max-w-lg rounded-lg border border-red-800 bg-neutral-950 p-6">
            <h1 className="mb-2 text-lg font-bold text-red-400">UI crashed</h1>
            <pre className="mb-4 whitespace-pre-wrap text-xs text-neutral-400">
              {String(this.state.error)}
            </pre>
            <button
              className="rounded bg-emerald-700 px-3 py-1 text-sm text-white"
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

// ---------- components ----------

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
        <h1 className="mb-4 text-center text-lg font-bold text-emerald-400">CodingDude</h1>
        <input
          type="password"
          className="mb-3 w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
        />
        {err && <div className="mb-2 text-xs text-red-400">{err}</div>}
        <button className="w-full rounded bg-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600">
          Log in
        </button>
      </form>
    </div>
  )
}

function Sidebar({ workdir, setWorkdir, sessions, activeSession, onSelect, onNewSession }) {
  return (
    <aside className="w-64 shrink-0 border-r border-neutral-800 bg-neutral-950 p-3 flex flex-col gap-3">
      <h1 className="text-lg font-bold text-emerald-400">CodingDude</h1>
      <label className="text-xs text-neutral-400">
        Workdir
        <input
          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-200"
          value={workdir}
          onChange={(e) => setWorkdir(e.target.value)}
          placeholder="C:\path\to\project"
        />
      </label>
      <button
        className="rounded bg-emerald-700 px-2 py-1 text-sm font-medium text-white hover:bg-emerald-600"
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
                ? 'bg-neutral-800 text-emerald-300'
                : 'text-neutral-400 hover:bg-neutral-900'
            }`}
            onClick={() => onSelect(s.session_id)}
            title={s.title || s.session_id}
          >
            {s.title || s.session_id.slice(0, 12)}
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
    <div className="my-1 rounded border border-neutral-800 bg-neutral-900/50 text-xs">
      <button
        className="w-full px-2 py-1 text-left text-neutral-400 hover:text-neutral-200"
        onClick={() => setOpen(!open)}
      >
        {open ? '▾' : '▸'} {events.length} tool call{events.length > 1 ? 's' : ''}
      </button>
      {open && (
        <div className="space-y-1 px-2 pb-2">
          {events.map((e, i) => (
            <div key={i} className="rounded bg-neutral-950 p-1 font-mono text-neutral-400">
              <div className="text-emerald-500">{e.tool_name || e.type}</div>
              {e.result && <pre className="whitespace-pre-wrap text-neutral-500">{e.result}</pre>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ApprovalCard({ command, onDecide }) {
  return (
    <div className="my-2 rounded border border-amber-600 bg-amber-900/20 p-3">
      <div className="mb-2 text-xs font-semibold text-amber-300">Approval needed</div>
      <pre className="mb-2 overflow-x-auto rounded bg-neutral-950 p-2 font-mono text-xs text-neutral-200">{command}</pre>
      <div className="flex gap-2">
        <button className="rounded bg-emerald-700 px-3 py-1 text-xs text-white hover:bg-emerald-600"
          onClick={() => onDecide('approve')}>Approve</button>
        <button className="rounded bg-neutral-700 px-3 py-1 text-xs text-white hover:bg-neutral-600"
          onClick={() => onDecide('pattern')}>Approve all matching</button>
        <button className="rounded bg-red-800 px-3 py-1 text-xs text-white hover:bg-red-700"
          onClick={() => onDecide('deny')}>Deny</button>
      </div>
    </div>
  )
}

function PlanCard({ sessionId }) {
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
  const statusColor = plan.status === 'rejected' ? 'text-red-400'
    : plan.status === 'done' ? 'text-emerald-400' : 'text-amber-300'
  return (
    <div className="my-2 rounded border border-sky-700 bg-sky-900/20 p-3">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-semibold text-sky-300">Plan — {plan.goal}</span>
        <span className={`text-xs ${statusColor}`}>{plan.status}</span>
      </div>
      <ol className="space-y-0.5">
        {plan.steps.map((s, i) => (
          <li key={i} className="text-xs text-neutral-300">
            {s.status === 'done' ? '☑' : '☐'} {s.text}
          </li>
        ))}
      </ol>
    </div>
  )
}

function Chat({ messages, streaming, onStop, onDecide, sessionId }) {
  const [pendingPlan, setPendingPlan] = useState(null)
  // A gate whose command starts with "plan:" is a plan approval — poll the
  // plan endpoint so the card renders the actual steps.
  useEffect(() => {
    const gate = messages.find((m) => m.gate && m.gate.startsWith('plan:'))
    setPendingPlan(gate ? gate.gate : null)
  }, [messages])
  const bottomRef = useRef(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
            <div
              className={`inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                m.role === 'user'
                  ? 'bg-emerald-800 text-white'
                  : 'bg-neutral-800 text-neutral-200'
              }`}
            >
              {m.text}
              {m.streaming && <span className="animate-pulse">▍</span>}
            </div>
            {m.toolEvents && <ToolTimeline events={m.toolEvents} />}
            {m.review && (
              <div className="my-1 rounded border border-purple-700 bg-purple-900/20 p-2 text-xs">
                <div className="font-semibold text-purple-300">Reviewer findings</div>
                <pre className="whitespace-pre-wrap text-neutral-300">{m.review}</pre>
              </div>
            )}
            {m.gate && !m.gate.startsWith('plan:') && <ApprovalCard command={m.gate} onDecide={onDecide} />}
            {m.gate && m.gate.startsWith('plan:') && sessionId && <PlanCard sessionId={sessionId} />}
            {m.gate && m.gate.startsWith('plan:') && (
              <div className="my-1 flex gap-2">
                <button className="rounded bg-emerald-700 px-3 py-1 text-xs text-white hover:bg-emerald-600"
                  onClick={() => onDecide('approve')}>Approve plan</button>
                <button className="rounded bg-red-800 px-3 py-1 text-xs text-white hover:bg-red-700"
                  onClick={() => onDecide('deny')}>Reject</button>
              </div>
            )}
          </div>
        ))}
        {streaming && (
          <button
            className="rounded border border-red-700 px-2 py-1 text-xs text-red-400 hover:bg-red-900/30"
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

// ---------- file explorer ----------

function TreeNode({ node, depth, onOpen }) {
  const [open, setOpen] = useState(depth < 1)
  if (node.type === 'dir') {
    return (
      <div>
        <button
          className="block w-full truncate text-left text-xs text-sky-300 hover:text-sky-200"
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
      className="block w-full truncate text-left text-xs text-neutral-300 hover:text-white"
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
  const [file, setFile] = useState(null) // {path, content, is_markdown}
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
            <span className="truncate font-mono text-[10px] text-emerald-300">{openPath}</span>
            <div className="flex gap-1">
              {file?.is_markdown && !editing && (
                <button
                  className="rounded bg-neutral-700 px-2 py-0.5 text-[10px] text-white"
                  onClick={() => setEditing(!editing)}
                >{editing ? 'view' : 'edit'}</button>
              )}
              {!file?.is_markdown && (
                <button
                  className="rounded bg-neutral-700 px-2 py-0.5 text-[10px] text-white"
                  onClick={() => { setDraft(file?.content || ''); setEditing(!editing) }}
                >{editing ? 'cancel' : 'edit'}</button>
              )}
              {editing && (
                <button
                  className="rounded bg-emerald-700 px-2 py-0.5 text-[10px] text-white"
                  onClick={save}
                >save</button>
              )}
            </div>
          </div>
          {saved && <div className="text-[10px] text-emerald-400">saved ✓</div>}
          {editing ? (
            <textarea
              className="min-h-0 flex-1 resize-none rounded border border-neutral-700 bg-neutral-900 p-2 font-mono text-[11px] text-neutral-200"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
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

function RightPanel({ sessionId, refreshKey }) {
  const tabs = ['Diff', 'Files', 'Terminal', 'Cost', 'Memory', 'MCP', 'Standards']
  const [tab, setTab] = useState('Diff')
  const [data, setData] = useState({})
  const fileKey = `${refreshKey}`

  async function toggleServer(name, disabled) {
    await api.toggleMcp(sessionId, name, disabled).catch((e) => setError)
    setData({ mcp: await api.listMcp(sessionId) })
  }

  // Standards poll (directives + review checklist) — the visible methodology.
  useEffect(() => {
    if (tab !== 'Standards' || !sessionId) return
    let stop = false
    call(`/sessions/${sessionId}/standards`)
      .then((d) => { if (!stop) setData({ standards: d }) })
      .catch(() => {})
    return () => { stop = true }
  }, [sessionId, tab, refreshKey])

  let body = <div className="text-neutral-600">nothing yet</div>
  if (tab === 'Standards') {
    const st = data.standards
    body = st ? (
      <div className="space-y-2">
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-400">
            Active directives (enforced on every run)
          </div>
          <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded bg-neutral-900 p-2 text-[11px] text-neutral-300">
            {st.layers || '(no DIRECTIVES.md / AGENT.md found — add rules to activate)'}
          </pre>
        </div>
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-purple-400">
            Review checklist (applied before work is accepted)
          </div>
          <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded bg-neutral-900 p-2 text-[11px] text-neutral-400">
            {st.review_checklist}
          </pre>
        </div>
        <div className="text-[10px] text-neutral-600">
          edit via {st.layers && st.layers.includes('AGENT.md') ? 'AGENT.md' : '~/.codingdude/DIRECTIVES.md'} — agent edits require your approval
        </div>
      </div>
    ) : <div className="text-neutral-600">loading…</div>
  } else if (tab === 'Terminal') {
    body = <div className="text-neutral-600">command output lives in the chat tool timeline</div>
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
              className={s.disabled ? 'text-emerald-500 hover:text-emerald-300' : 'text-red-500 hover:text-red-300'}
              onClick={() => toggleServer(s.name, !s.disabled)}
            >{s.disabled ? 'enable' : 'disable'}</button>
          </div>
        ))}
        <div className="text-neutral-600">config: ~/.codingdude/mcp.json (global) + .codingdude/mcp.json (project)</div>
      </div>
    )
  } else if (tab === 'Diff' && data.diff) {
    body = (
      <pre className="whitespace-pre-wrap font-mono text-[10px] leading-tight">
        {data.diff.split('\n').map((l, i) => (
          <div key={i} className={l.startsWith('+') ? 'text-emerald-400' : l.startsWith('-') ? 'text-red-400' : 'text-neutral-500'}>{l}</div>
        ))}
      </pre>
    )
  } else if (tab === 'Files') {
    body = <FileExplorer sessionId={sessionId} />
  } else if (tab === 'Cost' && data.usage) {
    const u = data.usage
    body = (
      <div className="space-y-1 text-neutral-300">
        <div>requests: {u.requests ?? 0}</div>
        <div>input tokens: {u.input_tokens ?? 0}</div>
        <div>output tokens: {u.output_tokens ?? 0}</div>
        <div className="text-emerald-400">cost: ${(u.cost_usd ?? 0).toFixed(4)}</div>
      </div>
    )
  } else if (tab === 'Memory' && data.memory) {
    body = (
      <div className="space-y-1">
        {data.memory.map((m) => (
          <div key={m.id} className="flex items-start justify-between gap-1 rounded bg-neutral-900 p-1">
            <span className="text-neutral-300">{m.content}</span>
            <button
              className="text-red-500 hover:text-red-300"
              onClick={() => call(`/memory/${m.id}`, { method: 'DELETE' }).then(() => setData({ memory: data.memory.filter((x) => x.id !== m.id) }))}
            >✕</button>
          </div>
        ))}
      </div>
    )
  }
  return (
    <aside className="w-80 shrink-0 overflow-y-auto border-l border-neutral-800 bg-neutral-950 p-3">
      <div className="mb-2 flex flex-wrap gap-1">
        {tabs.map((t) => (
          <button
            key={t}
            className={`rounded px-2 py-1 text-xs ${tab === t ? 'bg-neutral-800 text-emerald-300' : 'text-neutral-500 hover:text-neutral-300'}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="text-xs">{body}</div>
    </aside>
  )
}

// ---------- app ----------

export default function App() {
  const [loggedIn, setLoggedIn] = useState(null) // null = checking cookie
  const [workdir, setWorkdir] = useState(localStorage.getItem('codingdude-workdir') || '')
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const runRef = useRef(null)
  const esRef = useRef(null)

  // Any 401 from the API bounces back to the login screen.
  useEffect(() => {
    const onUnauthorized = () => setLoggedIn(false)
    window.addEventListener('cd-unauthorized', onUnauthorized)
    return () => window.removeEventListener('cd-unauthorized', onUnauthorized)
  }, [])

  // On load: an existing session cookie skips the login screen.
  useEffect(() => {
    checkAuth().then((ok) => {
      setLoggedIn(ok)
      if (ok) refreshSessions(workdir)
    })
  }, [])

  // Poll the panels while a run streams (diff/cost change live).
  useEffect(() => {
    if (!streaming) return
    const t = setInterval(() => setRefreshKey((k) => k + 1), 4000)
    return () => clearInterval(t)
  }, [streaming])

  const refreshSessions = useCallback(async (wd) => {
    if (!wd) return
    try {
      setSessions(await api.listSessions(wd))
      setError('')
    } catch (e) {
      setError(String(e.message))
    }
  }, [])

  useEffect(() => {
    if (loggedIn) refreshSessions(workdir)
  }, [loggedIn, workdir, refreshSessions])

  async function loadMessages(sessionId) {
    // Server messages are the canonical history; render them as chat turns.
    const raw = await api.getMessages(sessionId)
    const turns = []
    for (const m of raw) {
      for (const p of m.parts || []) {
        if (p.part_kind === 'user-prompt') {
          turns.push({ role: 'user', text: p.content })
        } else if (p.part_kind === 'text' && m.kind === 'response') {
          turns.push({ role: 'assistant', text: p.content })
        }
      }
    }
    setMessages(turns)
  }

  function newSession() {
    if (!workdir) return
    localStorage.setItem('codingdude-workdir', workdir)
    api
      .createSession(workdir)
      .then((r) => {
        setActiveSession(r.session_id)
        setMessages([])
        refreshSessions(workdir)
      })
      .catch((e) => setError(String(e.message)))
  }

  function send(prompt) {
    if (!activeSession || streaming) return
    setMessages((m) => [...m, { role: 'user', text: prompt }, { role: 'assistant', text: '', streaming: true, toolEvents: [] }])
    setStreaming(true)
    setError('')
    api
      .startRun(activeSession, prompt)
      .then(({ run_id }) => {
        runRef.current = run_id
        const es = new EventSource(api.eventStreamUrl(run_id))
        esRef.current = es
        es.onmessage = (e) => {
          const ev = JSON.parse(e.data)
          setMessages((msgs) => {
            const copy = [...msgs]
            const last = { ...copy[copy.length - 1] }
            if (ev.type === 'TEXT_MESSAGE_CONTENT') last.text += ev.delta
            if (ev.type === 'TOOL_CALL_END')
              last.toolEvents = [
                ...(last.toolEvents || []),
                { tool_name: ev.tool_name, result: ev.result },
              ]
            if (ev.type === 'GATE_REQUEST') last.gate = ev.command
            if (ev.type === 'REVIEW_FINDINGS') last.review = ev.findings
            // The gate card clears only when the tool actually finishes —
            // TOOL_CALL_START fires *before* the gate resolves, so clearing
            // on it would erase the card the moment it appears.
            if (ev.type === 'TOOL_CALL_END') last.gate = null
            if (ev.type === 'RUN_ERROR') setError(ev.message || 'run error')
            if (ev.type in { RUN_FINISHED: 1, RUN_ERROR: 1, RUN_CANCELLED: 1 }) {
              last.streaming = false
              es.close()
              setStreaming(false)
              loadMessages(activeSession) // canonical history replaces the stream
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

  function stop() {
    if (runRef.current) api.cancelRun(runRef.current).catch(() => {})
    esRef.current?.close()
    setStreaming(false)
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
    <div className="flex h-screen bg-neutral-900 text-neutral-200">
      <Sidebar
        workdir={workdir}
        setWorkdir={setWorkdir}
        sessions={sessions}
        activeSession={activeSession}
        onSelect={(id) => {
          setActiveSession(id)
          loadMessages(id).catch((e) => setError(String(e.message)))
        }}
        onNewSession={newSession}
      />
      <main className="flex flex-1 flex-col overflow-hidden">
        {error && <div className="bg-red-900/50 px-4 py-1 text-xs text-red-300">{error}</div>}
        <Prompt onSend={send} disabled={!activeSession || streaming} />
        <Chat
          sessionId={activeSession}
          messages={messages}
          streaming={streaming}
          onStop={stop}
          onDecide={(decision) => {
            setMessages((msgs) => {
              const copy = [...msgs]
              const last = { ...copy[copy.length - 1] }
              last.gate = null
              copy[copy.length - 1] = last
              return copy
            })
            if (runRef.current) api.approve(runRef.current, decision).catch((e) => setError(String(e.message)))
          }}
        />
      </main>
      <RightPanel sessionId={activeSession} refreshKey={refreshKey} />
    </div>
  )
}

function Prompt({ onSend, disabled }) {
  const [text, setText] = useState('')
  return (
    <form
      className="flex gap-2 border-b border-neutral-800 p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (text.trim()) {
          onSend(text.trim())
          setText('')
        }
      }}
    >
      <input
        className="flex-1 rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={disabled ? 'create or select a session first' : 'describe the task…'}
        disabled={disabled}
      />
      <button
        className="rounded bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-40"
        disabled={disabled}
      >
        Send
      </button>
    </form>
  )
}
