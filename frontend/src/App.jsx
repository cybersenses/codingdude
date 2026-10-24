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
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, authLocal, call, checkAuth } from './api'
import { SSE_MAX_RETRIES, runToReattach, sseRetryDelayMs } from './reattach'
import { activeProcesses, mergeProcesses } from './processes'
import { PANE_SPECS, paneWidth } from './panes'
import { groupEventsByRun, pickRunId } from './runs'
import { pickPending } from './pending'
import { clearPendingPrompts } from './askUser'
import { pendingArtifacts } from './artifacts'
import { buildSpans } from './waterfall'
import { buildTour } from './tour'
import { buildDesignDocPrompt } from './designdoc'
import { callgraphMermaid, graphView } from './callgraph'
import { cfgMermaid } from './cfgView'
import { buildRepoQuestionPrompt } from './repoqa'
import { structureRows } from './structure'
import { Mermaid } from './ui.jsx'

// Chrome (fixed surfaces) and panels (dockable in P1). App keeps only the
// session/SSE state machine and the layout; every visible surface lives in
// its own module.
import { Login } from './chrome/Login.jsx'
import { Sidebar } from './chrome/Sidebar.jsx'
import { AgentStrip } from './chrome/AgentStrip.jsx'
import { StatusFooter } from './chrome/StatusFooter.jsx'
import { PendingArtifactCard } from './cards/chatCards.jsx'
import { FileTree } from './panels/Explorer.jsx'
import { EditorPane } from './panels/Editor.jsx'
import { Chat } from './panels/Chat.jsx'
import { Prompt } from './panels/Prompt.jsx'
import { useFileWorkspace } from './store/useFileWorkspace.js'

import { Terminal } from './panels/dock/Terminal.jsx'
import { Notes } from './panels/dock/Notes.jsx'

import { Artifacts } from './panels/dock/Artifacts.jsx'
import { ModelsConfig } from './panels/dock/ModelsConfig.jsx'
import { Planning } from './panels/dock/Planning.jsx'
import { Standards } from './panels/dock/Standards.jsx'
import { DiffPanel } from './panels/dock/Diff.jsx'

// #229: how many memory entries the dock renders. The table grows forever
// (one entry per remembered fact/solution), and the whole list is rebuilt on
// every 4s poll — 2,144 entries meant 15.8k DOM nodes versus 810 for Diff.
const MEMORY_LIMIT = 200

// R35 #72: bottom dock — VS Code panel position. Processes comes in as a
// prop (App polls it); it used to be a bare-identifier crash in this scope.
function DockPanel({ sessionId, refreshKey, diffBadge, artifactsPending = 0, workdir, processes, height, onResizeHeight, focusDiff = 0, activePath = '', onAsk }) {
  const [repoQuestion, setRepoQuestion] = useState('')
  // #227: Processes was wired (prop + body) but missing from this list, so its
  // body was unreachable. It renders from App's 3s poll, not DockPanel's.
  const tabs = ['Diff', 'Graph', 'Planning', 'Artifacts', 'Notes', 'Renders', 'Terminal', 'Processes', 'Output', 'Waterfall', 'Trace', 'Cost', 'Memory', 'MCP', 'Config', 'Standards']
  const [tab, setTab] = useState('Diff')
  const [data, setData] = useState({})

  // R35 #75: "review agent changes" bumps focusDiff to switch to the Diff tab.
  useEffect(() => {
    if (focusDiff > 0) setTab('Diff')
  }, [focusDiff])

  useEffect(() => {
    // R50: model config is session-independent — load it without a session.
    // #228: memory is too (global + every workdir), so it loads on a fresh
    // workspace instead of being gated behind a session it does not need.
    if (!sessionId && (tab === 'Config' || tab === 'Memory')) {
      ;(async () => {
        try {
          if (tab === 'Config') {
            const r = await call('/config/models')
            setData((d) => ({ ...d, config: r, configError: undefined }))
          } else {
            const m = await call('/memory')
            setData((d) => ({ ...d, memory: m, memoryError: undefined }))
          }
        } catch (err) {
          const msg = String(err instanceof Error ? err.message : err)
          if (tab === 'Config') setData((d) => ({ ...d, configError: msg }))
          else setData((d) => ({ ...d, memoryError: msg }))
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
        if (tab === 'Memory') { const m = await call('/memory'); setData((d) => ({ ...d, memory: m, memoryError: undefined })) }
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


  let body = (
    <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">
      Select a session to see diffs, files, cost and trace.
    </div>
  )
  if (tab === 'Standards') {
    body = <Standards sessionId={sessionId} />
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
  } else if (tab === 'Memory') {
    // #228: the tab polled /memory but had no body branch — it rendered the
    // "select a session" placeholder forever. Facts and solutions the agent
    // recalls across sessions, newest first (server order).
    // #229: the whole table is rendered on every 4s poll — capped at the
    // newest MEMORY_LIMIT entries, which is what a human scrolls anyway.
    const entries = data.memory
    const shown = (entries || []).slice(0, MEMORY_LIMIT)
    body = (
      <div className="space-y-1">
        <div className="flex items-baseline gap-2 font-mono text-[10px] uppercase tracking-wide text-ink-muted">
          <span>
            {entries === undefined
              ? 'loading…'
              : shown.length < entries.length
                ? `showing newest ${shown.length} of ${entries.length} entries`
                : `${entries.length} ${entries.length === 1 ? 'entry' : 'entries'}`}
          </span>
          <span className="ml-auto normal-case">facts and solutions recalled across sessions</span>
        </div>
        {data.memoryError && <div className="text-danger">{data.memoryError}</div>}
        {entries && !entries.length && (
          <div className="rounded border border-line bg-surface p-4 text-ink-muted">
            No memory entries yet. The agent remembers facts mid-run and banks solutions it has proved.
          </div>
        )}
        {shown.map((m) => (
          <div key={m.id} className="rounded border border-line bg-surface p-1.5">
            <div className="flex flex-wrap items-baseline gap-2 font-mono text-[10px]">
              <span className={m.kind === 'solution' ? 'text-accent' : 'text-brand-300'}>{m.kind || 'fact'}</span>
              <span className="text-ink-muted">{m.scope}</span>
              {m.workdir && (
                <span className="min-w-0 truncate text-ink-muted" title={m.workdir}>
                  {m.workdir.split(/[\\/]/).filter(Boolean).pop()}
                </span>
              )}
              <span className="ml-auto shrink-0 text-ink-muted">{(m.created_at || '').replace('T', ' ').slice(0, 16)}</span>
            </div>
            <div className="mt-0.5 whitespace-pre-wrap break-words text-[11px] text-ink">{m.content}</div>
          </div>
        ))}
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
    body = <DiffPanel diff={data.diff} diffSummary={data.diffSummary} impact={data.impact} />
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
      <StatusFooter
        activeSession={activeSession}
        sessions={sessions}
        workdir={workdir}
        srv={srv}
        theme={theme}
        onToggleTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
        processes={processes}
      />
    </div>
  )
}

