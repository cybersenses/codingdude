import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, getToken, setToken } from './api.js'

// ---------- components ----------

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
      <TokenBox />
    </aside>
  )
}

function TokenBox() {
  const [value, setValue] = useState(getToken())
  return (
    <label className="text-xs text-neutral-500">
      Server token
      <input
        className="mt-1 w-full rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs text-neutral-400"
        type="password"
        value={value}
        onChange={(e) => {
          setValue(e.target.value)
          setToken(e.target.value)
        }}
        placeholder="paste token"
      />
    </label>
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

function Chat({ messages, streaming, onStop }) {
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

function RightPanel({ placeholder }) {
  const tabs = ['Diff', 'Files', 'Terminal', 'Cost']
  const [tab, setTab] = useState('Cost')
  return (
    <aside className="w-80 shrink-0 border-l border-neutral-800 bg-neutral-950 p-3">
      <div className="mb-2 flex gap-1">
        {tabs.map((t) => (
          <button
            key={t}
            className={`rounded px-2 py-1 text-xs ${
              tab === t ? 'bg-neutral-800 text-emerald-300' : 'text-neutral-500 hover:text-neutral-300'
            }`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="text-xs text-neutral-500">{placeholder[tab]}</div>
    </aside>
  )
}

// ---------- app ----------

export default function App() {
  const [workdir, setWorkdir] = useState(localStorage.getItem('codingdude-workdir') || '')
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState('')
  const runRef = useRef(null)
  const esRef = useRef(null)

  const refreshSessions = useCallback(async (wd) => {
    if (!wd) return
    try {
      setSessions(await api.listSessions(wd))
    } catch (e) {
      setError(String(e.message))
    }
  }, [])

  useEffect(() => {
    refreshSessions(workdir)
  }, [workdir, refreshSessions])

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

  const placeholder = {
    Diff: 'Working-tree diff appears here (ticket 10).',
    Files: 'Workdir file tree appears here (ticket 10).',
    Terminal: 'Command output streams here (ticket 10).',
    Cost: 'Per-session tokens and cost appear here (ticket 10).',
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
        <Chat messages={messages} streaming={streaming} onStop={stop} />
      </main>
      <RightPanel placeholder={placeholder} />
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
