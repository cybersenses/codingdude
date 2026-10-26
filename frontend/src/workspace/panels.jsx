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
// R59 P2: the dock panels for topics served by the visibility-gated store
// (tech design #1 §4.3). Each body was ported from the retired DockPanel
// tab body, unchanged in what it renders; what changed is the data source —
// useSessionData(store, topic, sessionId) instead of the per-tab 4s poll.
//
// The store's error model replaced DockPanel's banner seam: a snapshot error
// renders through `data-poll-error` (the same attribute tools/ui_smoke.py
// gates on), and the last successful data is kept beside it, so a failed
// refresh never looks like "no data yet" (#231/#234).
import React, { useEffect, useState } from 'react'
import { api, call } from '../api'
import { activeProcesses, mergeProcesses } from '../processes'
import { groupEventsByRun, pickRunId } from '../runs'
import { buildSpans } from '../waterfall'
import { buildTour } from '../tour'
import { buildDesignDocPrompt } from '../designdoc'
import { callgraphMermaid, graphView } from '../callgraph'
import { cfgMermaid } from '../cfgView'
import { buildRepoQuestionPrompt } from '../repoqa'
import { structureRows } from '../structure'
import { Mermaid } from '../ui.jsx'
import { useSessionData } from '../store/sessionData'
import { MEMORY_LIMIT } from '../limits'
import { Terminal } from '../panels/dock/Terminal.jsx'
import { Notes } from '../panels/dock/Notes.jsx'
import { Artifacts } from '../panels/dock/Artifacts.jsx'
import { Planning } from '../panels/dock/Planning.jsx'
import { Standards } from '../panels/dock/Standards.jsx'
import { ModelsConfig } from '../panels/dock/ModelsConfig.jsx'
import { DiffPanel } from '../panels/dock/Diff.jsx'

// Shared shell access: { store, sessionId, workdir, activePath, onAsk }.
// Provided by Workspace.jsx's WorkspaceContext — see the note there on why
// panels read context rather than dockview params.
import { useShell } from './shellContext'

// ---------------------------------------------------------------------------
// Shared plumbing
// ---------------------------------------------------------------------------

const NO_SESSION = (
  <div className="p-2 text-xs text-ink-muted">
    Select a session to see diffs, files, cost and trace.
  </div>
)

function PollErrorBanner({ topic, error }) {
  // `data-poll-error` is the seam tools/ui_smoke.py fails on: without it, a
  // panel whose fetch is failing passes the gate looking healthy.
  return (
    <div
      data-poll-error={topic}
      className="rounded border border-danger/40 bg-danger/10 p-3 text-xs text-danger"
    >
      could not load this tab: {error}
    </div>
  )
}

// Wraps a store topic: placeholder without a session, banner on error, body
// once data exists (stale data still shown beside a failed refresh).
export function TopicPanel({ topic, children }) {
  const { store, sessionId } = useShell()
  const snap = useSessionData(store, topic, sessionId)
  if (!sessionId) return NO_SESSION
  return (
    <div data-panel={topic} className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      {snap.error && <PollErrorBanner topic={topic} error={snap.error} />}
      {snap.data
        ? children(snap.data)
        : !snap.error && <div className="rounded border border-line bg-surface p-4 text-ink-muted">loading…</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Diff
// ---------------------------------------------------------------------------

export function DiffStorePanel() {
  return <TopicPanel topic="diff">{(d) => <DiffPanel {...d} />}</TopicPanel>
}

// ---------------------------------------------------------------------------
// Cost
// ---------------------------------------------------------------------------

export function CostPanel() {
  return (
    <TopicPanel topic="cost">
      {(usage) => (
        <div className="space-y-1">
          <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">requests</span><span className="text-ink">{usage.requests ?? 0}</span></div>
          <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">input tokens</span><span className="text-ink">{usage.input_tokens ?? 0}</span></div>
          <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">output tokens</span><span className="text-ink">{usage.output_tokens ?? 0}</span></div>
          <div className="flex justify-between font-mono text-xs"><span className="text-ink-muted">cost (usd)</span><span className="text-brand-400">${(usage.cost_usd ?? 0).toFixed(4)}</span></div>
          {(usage.by_model || []).length > 0 && (
            <div className="mt-2">
              <div className="text-[10px] font-semibold uppercase text-ink-muted">by model</div>
              {(usage.by_model || []).map((m) => (
                <div key={m.model} className="flex justify-between font-mono text-[10px] text-ink-muted">
                  <span className="truncate">{m.model}</span>
                  <span className="ml-2 shrink-0">{m.requests} req · {m.input_tokens}/{m.output_tokens} tok · ${(m.cost_usd ?? 0).toFixed(4)}</span>
                </div>
              ))}
            </div>
          )}
          {(usage.by_request || []).length > 0 && (
            <div className="mt-2">
              <div className="text-[10px] font-semibold uppercase text-ink-muted">per request</div>
              {(usage.by_request || []).map((r, i) => (
                <div key={i} className="flex justify-between font-mono text-[10px] text-ink-muted">
                  <span className="truncate">{i + 1}. {r.model}</span>
                  <span className="ml-2 shrink-0">{r.requests} req · {r.input_tokens}/{r.output_tokens} tok · ${(r.cost_usd ?? 0).toFixed(4)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </TopicPanel>
  )
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export function MemoryPanel() {
  return (
    <TopicPanel topic="memory">
      {(entries) => {
        const shown = (entries || []).slice(0, MEMORY_LIMIT)
        return (
          <div className="space-y-1">
            <div className="flex items-baseline gap-2 font-mono text-[10px] uppercase tracking-wide text-ink-muted">
              <span>
                {shown.length < entries.length
                  ? `showing newest ${shown.length} of ${entries.length} entries`
                  : `${entries.length} ${entries.length === 1 ? 'entry' : 'entries'}`}
              </span>
              <span className="ml-auto normal-case">facts and solutions recalled across sessions</span>
            </div>
            {!entries.length && (
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
      }}
    </TopicPanel>
  )
}

// ---------------------------------------------------------------------------
// MCP
// ---------------------------------------------------------------------------

export function McpPanel() {
  const { store, sessionId } = useShell()
  // #242 (R63): a failed enable/disable must not silently re-show the old
  // state — the same mutation-failure class fixed for Notes/Standards.
  const [mutError, setMutError] = useState(null)
  async function toggleServer(name, disabled) {
    setMutError(null)
    try {
      await api.toggleMcp(sessionId, name, disabled)
    } catch (err) {
      setMutError(err instanceof Error ? err.message : String(err))
      return // the refresh below would just re-show the unchanged state
    }
    store.refresh('mcp', sessionId)
  }
  return (
    <TopicPanel topic="mcp">
      {(mcp) => (
        <div className="space-y-1">
          {mutError && <PollErrorBanner topic="mcp" error={mutError} />}
          {mcp.length === 0 && <div className="text-neutral-600">no MCP servers configured</div>}
          {mcp.map((s) => (
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
      )}
    </TopicPanel>
  )
}

// ---------------------------------------------------------------------------
// Renders
// ---------------------------------------------------------------------------

export function RendersPanel() {
  const { sessionId } = useShell()
  return (
    <TopicPanel topic="renders">
      {({ renders: allRenders, renderStart }) => {
        const renders = allRenders || []
        renderStart = renderStart || 0
        const src = (r) => `/api/sessions/${sessionId}/render?path=${encodeURIComponent(r.path)}`
        const tile = (r, label) => (
          <a
            key={r.path}
            href={src(r)}
            target="_blank"
            rel="noreferrer"
            className="overflow-hidden rounded border border-line bg-surface hover:border-brand"
          >
            <img alt={r.name} loading="lazy" src={src(r)} className="h-24 w-full bg-canvas object-contain" />
            <div className="truncate px-1 py-0.5 font-mono text-[10px] text-ink-muted">
              {label ? `${label} · ` : ''}{r.path}
            </div>
          </a>
        )
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
              return mm && mm[1].toLowerCase() === m[1].toLowerCase() && mm[2].toLowerCase() === b
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
        return renders.length === 0 ? (
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
      }}
    </TopicPanel>
  )
}

// ---------------------------------------------------------------------------
// Trace
// ---------------------------------------------------------------------------

export function TracePanel() {
  const { sessionId } = useShell()
  // #242 (R63): a failed rewind is a user mutation, not a transient poll.
  const [rewindError, setRewindError] = useState(null)
  return (
    <TopicPanel topic="trace">
      {({ trace, checkpoints }) => {
        const colors = {
          GATE_REQUEST: 'text-warning', RUN_ERROR: 'text-danger',
          RUN_FINISHED: 'text-brand-400', TOOL_CALL_START: 'text-accent',
          TOOL_CALL_END: 'text-accent', PLAN_PROPOSED: 'text-accent',
          USER_PROMPT: 'text-neutral-300',
        }
        return (
          <div className="space-y-2">
            {rewindError && <PollErrorBanner topic="trace" error={rewindError} />}
            <div className="space-y-0.5 font-mono text-[10px]">
              {(trace || []).slice().reverse().map((e, i) => (
                <div key={i} className={`truncate rounded px-1 hover:bg-surface ${colors[e.type] || 'text-ink-muted'}`}>
                  <span className="text-ink-muted">{(e.ts || '').slice(11, 19)}</span> {e.type}{' '}
                  {e.command || e.tool_name || e.delta || ''}
                </div>
              ))}
              {(!trace || !trace.length) && <div className="px-1 text-ink-muted">no events yet</div>}
            </div>
            {checkpoints && checkpoints.length > 0 && (
              <div className="space-y-1 border-t border-neutral-800 pt-2">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-neutral-400">Checkpoints</div>
                {checkpoints.map((c) => (
                  <div key={c.id} className="rounded bg-neutral-900 p-1">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-[10px] text-neutral-300">{c.id.slice(0, 17)}</span>
                      <div className="flex gap-1">
                        <button
                          className="rounded bg-accent px-1.5 py-0.5 text-[9px] text-accent-fg"
                          onClick={() => call(`/checkpoints/${sessionId}/${c.id}/rewind`, { method: 'POST', body: '{}' })
                            .then(() => setRewindError(null))
                            .catch((err) => setRewindError(err instanceof Error ? err.message : String(err)))}
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
      }}
    </TopicPanel>
  )
}

// ---------------------------------------------------------------------------
// Output / Waterfall (both read the `output` topic)
// ---------------------------------------------------------------------------

function useOutputData() {
  const { store, sessionId } = useShell()
  return useSessionData(store, 'output', sessionId)
}

const statusColor = (s) => s === 'completed' ? 'text-success'
  : s === 'failed' ? 'text-danger'
  : s === 'interrupted' ? 'text-warning'
  : 'text-accent'

function RunButtons({ runs, runId, onPick }) {
  return (
    <div className="flex flex-wrap gap-1">
      {(runs || []).map((r) => (
        <button
          key={r.run_id}
          className={`rounded px-2 py-0.5 font-mono text-[10px] ${r.run_id === runId ? 'bg-neutral-800 text-brand-300' : 'text-neutral-500 hover:text-neutral-300'}`}
          onClick={() => onPick(r.run_id)}
          title={`${r.status}${r.exit_code != null ? ` (exit ${r.exit_code})` : ''} — started ${r.started_at}`}
        >
          {r.run_id} <span className={statusColor(r.status)}>{r.status}</span>
        </button>
      ))}
      {(!runs || !runs.length) && <span className="text-[10px] text-ink-muted">no runs recorded yet</span>}
    </div>
  )
}

export function OutputPanel() {
  const { sessionId, onAsk } = useShell()
  const snap = useOutputData()
  const [selRun, setSelRun] = useState(null)
  if (!sessionId) return NO_SESSION
  const runs = snap.data?.runs
  const runEvents = snap.data?.runEvents || []
  const groups = groupEventsByRun(runEvents)
  const runId = pickRunId(groups, selRun)
  const events = groups[runId] || []
  const statusOf = (rid) => (runs || []).find((r) => r.run_id === rid)?.status
  return (
    <div data-panel="output" className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      {snap.error && <PollErrorBanner topic="output" error={snap.error} />}
      {snap.data ? (
        <div className="flex h-full min-h-0 flex-col gap-2">
          <RunButtons runs={runs} runId={runId} onPick={setSelRun} />
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
      ) : !snap.error && <div className="rounded border border-line bg-surface p-4 text-ink-muted">loading…</div>}
    </div>
  )
}

export function WaterfallPanel() {
  const { sessionId } = useShell()
  const snap = useOutputData()
  const [selRun, setSelRun] = useState(null)
  if (!sessionId) return NO_SESSION
  const groups = groupEventsByRun(snap.data?.runEvents || [])
  const wfRunId = pickRunId(groups, selRun)
  const { spans, total } = buildSpans(groups[wfRunId] || [])
  const kindColor = (k) => k === 'edit' ? 'bg-brand-500' : k === 'gate' ? 'bg-warning' : k === 'tool' ? 'bg-accent' : 'bg-neutral-600'
  return (
    <div data-panel="waterfall" className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      {snap.error && <PollErrorBanner topic="output" error={snap.error} />}
      {snap.data ? (
        <div className="flex h-full min-h-0 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-1">
            <RunButtons runs={snap.data.runs} runId={wfRunId} onPick={setSelRun} />
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
      ) : !snap.error && <div className="rounded border border-line bg-surface p-4 text-ink-muted">loading…</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Processes
// ---------------------------------------------------------------------------

export function ProcessesPanel() {
  const { store, sessionId } = useShell()
  const snap = useSessionData(store, 'processes', sessionId)
  // App's poll merged each fetch into the previous list so an exited process
  // stays visible until the session changes, where classic *clears* the list;
  // the store replaces wholesale, so the merge — and the reset on a session
  // switch — live here now (post-push review: the reset was missing, bleeding
  // one project's exited rows into the next).
  const [merged, setMerged] = useState([])
  useEffect(() => {
    setMerged([])
  }, [sessionId])
  useEffect(() => {
    if (snap.data) setMerged((prev) => mergeProcesses(prev, snap.data))
  }, [snap.data])
  if (!sessionId) return NO_SESSION
  return (
    <div data-panel="processes" className="h-full min-h-0 overflow-y-auto p-3 text-xs">
      {snap.error && <PollErrorBanner topic="processes" error={snap.error} />}
      {activeProcesses(merged).length === 0 && (
        <p className="text-ink-muted">No running processes this session.</p>
      )}
      {activeProcesses(merged).map((p) => (
        <div key={`${p.pid}:${p.started_at}`} className="mb-1 rounded border border-neutral-800 p-2">
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
}

// ---------------------------------------------------------------------------
// Config (ModelsConfig keeps a local draft; store is the load path)
// ---------------------------------------------------------------------------

export function ConfigPanel() {
  const { store } = useShell()
  const snap = useSessionData(store, 'config', null)
  // ModelsConfig mutates through setData; a local mirror keeps its contract
  // while the store remains the poll/error source of truth.
  const [local, setLocal] = useState({})
  useEffect(() => {
    if (snap.data) setLocal((d) => ({ ...d, config: snap.data }))
  }, [snap.data])
  return (
    <div data-panel="config" className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      {snap.error && <PollErrorBanner topic="config" error={snap.error} />}
      {(snap.data || local.config) && <ModelsConfig data={local} setData={setLocal} />}
      {!snap.data && !local.config && !snap.error && (
        <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">loading…</div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Self-fetching panels (they already own their data + error surfaces)
// ---------------------------------------------------------------------------

export function TerminalPanel() {
  const { sessionId } = useShell()
  return (
    <div data-panel="terminal" className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      <Terminal sessionId={sessionId} />
    </div>
  )
}

export function NotesPanel() {
  const { sessionId, workdir } = useShell()
  return (
    <div data-panel="notes" className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      <Notes sessionId={sessionId} workdir={workdir} />
    </div>
  )
}

export function ArtifactsPanel() {
  const { sessionId } = useShell()
  return (
    <div data-panel="artifacts" className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      <Artifacts sessionId={sessionId} />
    </div>
  )
}

export function PlanningPanel() {
  const { workdir } = useShell()
  return (
    <div data-panel="planning" className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      <Planning workdir={workdir} />
    </div>
  )
}

export function StandardsPanel() {
  const { sessionId } = useShell()
  return (
    <div data-panel="standards" className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      <Standards sessionId={sessionId} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Graph — not yet a store topic: its fetch depends on activePath, which the
// store keys (topic, session) cannot express. It keeps the retired DockPanel's
// effect until the store grows a parametric key (deviation noted in
// code-design.md); the body is that tab body, verbatim.
// ---------------------------------------------------------------------------

const GRAPH_POLL_MS = 4000

export function GraphPanel() {
  const { sessionId, activePath, onAsk } = useShell()
  const [data, setData] = useState({})
  const [repoQuestion, setRepoQuestion] = useState('')
  useEffect(() => {
    if (!sessionId) return
    let stop = false
    async function poll() {
      try {
        if (activePath) {
          try {
            const g = await call(`/sessions/${sessionId}/callgraph?path=${encodeURIComponent(activePath)}`)
            setData((d) => ({ ...d, callgraph: g, callgraphPath: activePath, graphError: undefined }))
          } catch (err) {
            // Guard: only stamp graphError when there is no successful
            // callgraph for this path (a success for the same path clears it;
            // a success for a newer path must not be overwritten by this
            // older failure). The test must read the live state inside the
            // updater — `data` is frozen in this effect's closure.
            setData((d) => (d.callgraphPath === undefined || d.callgraphPath === activePath
              ? { ...d, graphError: String(err instanceof Error ? err.message : err) }
              : d))
          }
          try {
            const t = await call(`/sessions/${sessionId}/trust?path=${encodeURIComponent(activePath)}`)
            setData((d) => ({ ...d, trust: t, trustPath: activePath }))
          } catch { /* supplementary: leaves the trust bar empty */ }
          if (activePath.endsWith('.py')) {
            try {
              const cf = await call(`/sessions/${sessionId}/cfg?path=${encodeURIComponent(activePath)}`)
              setData((d) => ({ ...d, cfgFunctions: cf.functions || [], cfgFunctionsPath: activePath, cfg: undefined, cfgFn: undefined, cfgError: undefined }))
            } catch (err) {
              setData((d) => ({ ...d, cfgFunctions: [], cfgFunctionsPath: activePath, cfgError: String(err instanceof Error ? err.message : err) }))
            }
          }
        } else {
          const s = await call(`/sessions/${sessionId}/structure`)
          const a = await call(`/sessions/${sessionId}/archmap`)
          setData((d) => ({ ...d, structure: s, archmap: a }))
        }
      } catch { /* transient; next poll retries */ }
      if (!stop) setTimeout(poll, GRAPH_POLL_MS)
    }
    poll()
    return () => { stop = true }
  }, [sessionId, activePath])

  if (!sessionId) return NO_SESSION
  return (
    <div data-panel="graph" className="h-full min-h-0 overflow-y-auto p-2 text-xs">
      {activePath ? (
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
      )}
    </div>
  )
}
