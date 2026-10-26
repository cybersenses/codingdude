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
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { api, authLocal, call, checkAuth } from './api'
import { SSE_MAX_RETRIES, runToReattach, sseRetryDelayMs } from './reattach'
import { mergeProcesses } from './processes'
import { pickPending } from './pending'
import { clearPendingPrompts } from './askUser'
import { pendingArtifacts } from './artifacts'

// Chrome (fixed surfaces) and panels (dockable in P1). App keeps only the
// session/SSE state machine and the layout; every visible surface lives in
// its own module.
import { Login } from './chrome/Login.jsx'
import { useFileWorkspace } from './store/useFileWorkspace.js'
// R59 P4: the dockable shell is the only shell. Still lazy so the login page
// and the SSE state machine load before dockview (~98 KB gzip) does — the
// split is about startup order now, not about a second layout existing.
const Workspace = lazy(() =>
  import('./workspace/Workspace.jsx').then((m) => ({ default: m.Workspace })),
)

// R35 #72: bottom dock — VS Code panel position. Processes comes in as a
// prop (App polls it); it used to be a bare-identifier crash in this scope.
// R59 P4: the classic fifteen-tab DockPanel lived here. Every panel it
// hosted now ships in the dock shell (src/workspace/); its error seam
// survives as the per-panel [data-poll-error] banner and the store's
// per-topic errors.

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
  // R35 #72: shared file workspace — tree lives in the explorer panel, editor
  // in the editor panel; the dock shell owns all geometry (P4 removed the
  // classic resizable panes and panes.ts with it).
  const fileWs = useFileWorkspace(activeSession)


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

  // R59 P1: prop bags for the dock shell (historically shared with the
  // classic layout so the two could be compared). The dock is the only shell.
  const agentStripProps = {
    status: streaming ? status : 'idle',
    quietSeconds,
    hasChanges: diffBadge,
    streaming,
    onReviewChanges: () => setFocusDiffTab((n) => n + 1),
  }
  const sidebarProps = {
    projects,
    activeProject,
    workdir,
    setWorkdir,
    sessions,
    activeSession,
    runningSessions: new Set(runningSessions.keys()),
    onSelect: (id) => {
      setActiveSession(id) // history loads via the activeSession effect
    },
    onNewSession: newSession,
    onSelectProject: (p) => {
      setActiveProject(p)
      setWorkdir(p.workdir)
      setActiveSession(null)
      setMessages([])
      refreshSessions(p.workdir)
    },
    onAddProject: (name, wd) => {
      api.addProject(name, wd)
        .then((proj) => {
          setProjects((list) => [...list, proj].sort((a, b) => a.name.localeCompare(b.name)))
          setActiveProject(proj)
          setWorkdir(proj.workdir)
          setActiveSession(null)
          setMessages([])
        })
        .catch((e) => setError(String(e.message)))
    },
    onDeleteProject: (id) => {
      api.deleteProject(id).catch(() => {})
      setProjects((list) => list.filter((x) => x.id !== id))
      if (activeProject?.id === id) setActiveProject(null)
    },
  }
  const promptProps = {
    onSend: send,
    disabled: !activeSession || streaming,
    running: streaming,
    suggestMode,
    setSuggestMode: (v) => { setSuggestMode(v); localStorage.setItem('cd-suggest', v ? '1' : '0') },
    fixLoop,
    setFixLoop,
    models,
    model,
    setModel,
    yolo,
    setYolo,
    notify,
    toggleNotify,
  }
  const chatProps = {
    messages,
    streaming,
    onStop: stop,
    onDecide: decide,
    suggestMode,
    onEditRevert,
    runId: runRef.current,
  }
  const footerProps = {
    activeSession,
    sessions,
    workdir,
    srv,
    theme,
    onToggleTheme: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')),
    processes,
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

  // R59 P4: the dockable shell is the only shell. The Suspense stub shows
  // while the workspace chunk loads (login-first startup order).
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center bg-neutral-900 text-neutral-500">
          loading workspace…
        </div>
      }
    >
      <Workspace
        error={error}
        agentStrip={agentStripProps}
        sidebar={sidebarProps}
        fileWs={fileWs}
        onAsk={send}
        sessionId={activeSession}
        prompt={promptProps}
        pending={pending}
        chat={chatProps}
        footer={footerProps}
        reviewDiff={focusDiffTab}
        workdir={workdir}
        onRefreshArtifacts={() => {
          call(`/sessions/${activeSession}/artifacts`).then(setArtifactsAll).catch(() => {})
        }}
      />
    </Suspense>
  )
}

