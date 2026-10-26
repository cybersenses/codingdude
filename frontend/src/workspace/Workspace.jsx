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
// R59 (tech design #1 §4.2): the dockable shell — the only shell since P4
// retired the classic flexbox layout.
//
// Fixed chrome stays outside the dock — the error banner, AgentStrip and status
// footer describe the shell, not a panel, and every phase keeps them there.
import React, { useEffect, useRef, useState } from 'react'
import { DockviewReact, themeDark } from 'dockview-react'
import 'dockview-react/dist/styles/dockview.css'
import { DEFAULT_PRESET, panelSpec, presetById, isKnownPanel, panelListFor, panelOptions } from './catalogue'
import { runCommand } from './commands'
import { Sidebar } from '../chrome/Sidebar.jsx'
import { AgentStrip } from '../chrome/AgentStrip.jsx'
import { StatusFooter } from '../chrome/StatusFooter.jsx'
import { FileTree } from '../panels/Explorer.jsx'
import { EditorPane } from '../panels/Editor.jsx'
import { Chat } from '../panels/Chat.jsx'
import { Prompt } from '../panels/Prompt.jsx'
import { PendingArtifactCard } from '../cards/chatCards.jsx'
import { WorkspaceContext, useShell } from './shellContext'
import { createSessionStore } from '../store/sessionData'
import { sessionTopics, requiresSession } from '../store/sessionTopics'
import { CommandPalette } from './CommandPalette'
import {
  clearSavedLayout,
  createDebouncedSaver,
  loadSavedLayout,
  loadUserPresets,
  saveLayout,
  saveUserPreset,
} from './layoutStore'
import {
  ArtifactsPanel,
  ConfigPanel,
  CostPanel,
  DiffStorePanel,
  GraphPanel,
  McpPanel,
  MemoryPanel,
  NotesPanel,
  OutputPanel,
  PlanningPanel,
  ProcessesPanel,
  RendersPanel,
  StandardsPanel,
  TerminalPanel,
  TracePanel,
  WaterfallPanel,
} from './panels.jsx'

// One store per browser: the scheduler loop and its subscriber bookkeeping
// are module state, not React state. Disposal is unnecessary for a store that
// lives as long as the document does.
const store = createSessionStore(sessionTopics, { requiresSession })

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------

function NavPanel({ containerApi }) {
  const { sidebar, showPanel } = useShell()
  // R64: the panel list's open flags ride dockview's own add/remove events —
  // no polling, and a panel closed anywhere in the shell updates its row.
  const [openIds, setOpenIds] = useState(() => containerApi.panels.map((p) => p.id))
  useEffect(() => {
    const sync = () => setOpenIds(containerApi.panels.map((p) => p.id))
    const added = containerApi.onDidAddPanel(sync)
    const removed = containerApi.onDidRemovePanel(sync)
    return () => {
      added.dispose()
      removed.dispose()
    }
  }, [containerApi])
  // The dock owns the width now; Sidebar still wants an explicit one.
  // `data-panel` is what tools/ui_smoke.py asserts on — the tab bar existing is
  // not proof that a panel body rendered.
  return (
    <div data-panel="nav" className="flex h-full min-h-0 flex-col">
      <Sidebar
        width="100%"
        {...sidebar}
        panels={panelListFor(openIds)}
        onShowPanel={showPanel}
      />
    </div>
  )
}

function ExplorerPanel() {
  const { fileWs } = useShell()
  return (
    <div data-panel="explorer" className="flex h-full min-h-0 flex-col bg-neutral-950">
      <div className="shrink-0 px-2 py-1 text-[10px] uppercase tracking-wide text-ink-muted">Explorer</div>
      <FileTree sessionId={fileWs.sessionId} onOpen={(p) => fileWs.openFile(p)} />
    </div>
  )
}

function EditorPanel() {
  const { fileWs, onAsk } = useShell()
  return (
    <div data-panel="editor" className="flex h-full min-h-0 flex-col overflow-hidden bg-neutral-950">
      <EditorPane ws={fileWs} onAsk={onAsk} />
    </div>
  )
}

function ChatPanel() {
  const { sessionId, prompt, pending, chat, onRefreshArtifacts } = useShell()
  return (
    <div data-panel="chat" className="flex h-full min-h-0 flex-col overflow-hidden bg-neutral-950">
      <Prompt {...prompt} />
      <PendingArtifactCard items={pending} onResponded={onRefreshArtifacts} />
      <Chat sessionId={sessionId} {...chat} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Visibility gating for store panels
// ---------------------------------------------------------------------------

// dockview keeps a background tab's panel mounted (its DOM stays in the
// document), so a panel's store subscription would keep polling a panel nobody
// can see — this is true of EVERY store panel, not only the `renderer:'always'`
// ones. dockview's onDidVisibilityChange flips the subscriber's visibility flag
// instead, so only panels on screen are ever fetched.
//
// The gate owns the visible count EXCLUSIVELY: the store's subscribe() does
// not touch it (post-push review fix — counting in both places
// double-decremented on unmount, leaving a still-visible sibling on a shared
// topic — Output + Waterfall both read `output` — unpolled). `countedRef`
// mirrors whether THIS subscriber is currently counted; the first sync(true)
// after mount performs the subscribe-time +1.
function visible(topic, Panel) {
  function GatedPanel(props) {
    const { store: shellStore, sessionId } = useShell()
    const panelApi = props.api
    const countedRef = useRef(false) // not yet counted visible
    useEffect(() => {
      const sync = (isVisible) => {
        if (isVisible === countedRef.current) return
        shellStore.setVisible(topic, sessionId, isVisible)
        countedRef.current = isVisible
      }
      if (!panelApi || typeof panelApi.onDidVisibilityChange !== 'function') {
        // No visibility signal available: assume on screen.
        sync(true)
        return () => sync(false)
      }
      const disp = panelApi.onDidVisibilityChange((ev) => sync(ev.isVisible))
      sync(panelApi.isVisible !== false)
      return () => {
        disp.dispose()
        sync(false)
      }
    }, [shellStore, sessionId, panelApi])
    return <Panel {...props} />
  }
  return GatedPanel
}

const GatedRendersPanel = visible('renders', RendersPanel)
const GatedConfigPanel = visible('config', ConfigPanel)
const GatedDiffPanel = visible('diff', DiffStorePanel)
const GatedCostPanel = visible('cost', CostPanel)
const GatedMemoryPanel = visible('memory', MemoryPanel)
const GatedMcpPanel = visible('mcp', McpPanel)
const GatedTracePanel = visible('trace', TracePanel)
const GatedOutputPanel = visible('output', OutputPanel)
const GatedWaterfallPanel = visible('output', WaterfallPanel)
const GatedProcessesPanel = visible('processes', ProcessesPanel)

// Module-level so the registry identity is stable across renders. Every key
// must have a catalogue entry and vice versa (catalogue.test.ts enforces it).
const COMPONENTS = {
  nav: NavPanel,
  explorer: ExplorerPanel,
  editor: EditorPanel,
  chat: ChatPanel,
  diff: GatedDiffPanel,
  graph: GraphPanel,
  planning: PlanningPanel,
  artifacts: ArtifactsPanel,
  notes: NotesPanel,
  renders: GatedRendersPanel,
  terminal: TerminalPanel,
  output: GatedOutputPanel,
  waterfall: GatedWaterfallPanel,
  trace: GatedTracePanel,
  cost: GatedCostPanel,
  memory: GatedMemoryPanel,
  mcp: GatedMcpPanel,
  config: GatedConfigPanel,
  standards: StandardsPanel,
  processes: GatedProcessesPanel,
}

// ---------------------------------------------------------------------------
// Preset application
// ---------------------------------------------------------------------------

// Builds an arrangement through the public addPanel API (see the note in
// catalogue.ts on why presets are placements, not serialized grid JSON).
//
// addPanel's `initialWidth` alone does not reproduce the classic geometry: the
// new group is created by splitting its reference and the sizes it lands on are
// proportional, which left the editor column ~115px wide with two ~500px
// columns beside it. So the fixed-size columns are pinned explicitly once the
// layout exists; the flexible middle keeps whatever is left.
function applyPresetPlacements(api, placements) {
  for (const placement of placements) {
    const spec = panelSpec(placement.id)
    if (!spec) continue
    api.addPanel({
      ...panelOptions(spec),
      initialWidth: placement.initialWidth,
      initialHeight: placement.initialHeight,
      ...(placement.referencePanel
        ? { position: { direction: placement.direction, referencePanel: placement.referencePanel } }
        : {}),
    })
  }
  // One frame later, so the groups have been laid out and setSize has actual
  // geometry to resize against.
  requestAnimationFrame(() => pinSizes(api, placements))
}

function pinSizes(api, placements) {
  for (const { id, initialWidth } of placements) {
    if (initialWidth !== undefined) api.getPanel(id)?.api.setSize({ width: initialWidth })
  }
  for (const { id, initialHeight } of placements) {
    if (initialHeight !== undefined) api.getPanel(id)?.api.setSize({ height: initialHeight })
  }
}

// Shown when every panel has been closed. REQ-8's escape hatch plus a way back
// to a known-good arrangement once drag-and-drop is in the user's hands.
function Watermark({ containerApi, onPreset }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-xs text-ink-muted">
      <p>Every panel is closed.</p>
      <button
        className="rounded bg-brand-700 px-3 py-1 text-xs text-brand-fg hover:bg-brand-600"
        onClick={() => onPreset(containerApi, 'default')}
      >
        Reset layout
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

const SAVE_DEBOUNCE_MS = 400

export function Workspace({ error, agentStrip, sidebar, fileWs, onAsk, sessionId, prompt, pending, chat, footer, onRefreshArtifacts, workdir, reviewDiff = 0 }) {
  const [api, setApi] = useState(null)
  const apiRef = useRef(null)
  // "layout reset (…)" / "dropped panels …" — surfaced once, dismissed by click.
  const [notice, setNotice] = useState(null)
  // Which preset the current layout derives from; saved with the layout so a
  // restore can label itself, and changed by any applyPreset.
  const presetRef = useRef('default')
  const [userPresets, setUserPresets] = useState(() => Object.keys(loadUserPresets(window.localStorage)))
  const saverRef = useRef(null)

  // #75's "Review changes →" bumps a counter in App; the shell answers it by
  // activating the `diff` panel, or the button would silently do nothing.
  useEffect(() => {
    if (reviewDiff > 0) apiRef.current?.getPanel('diff')?.api.setActive()
  }, [reviewDiff])

  // P3: applying a preset (palette, watermark reset) is one operation — the
  // pending debounced save must not resurrect the pre-apply snapshot after it.
  // Shipped presets are placements; user presets are serialized layouts
  // restored through fromJSON (with the same degrade-to-default guard).
  // `notice` may be null: the boot fallback for a *missing* layout is the
  // ordinary first-run path and must stay silent.
  function resetToDefault(targetApi, reason) {
    targetApi.clear()
    applyPresetPlacements(targetApi, DEFAULT_PRESET)
    presetRef.current = 'default'
    if (reason) setNotice(`layout reset (${reason})`)
  }

  function applyPresetByName(targetApi, presetId) {
    saverRef.current?.cancel()
    const preset = presetById(presetId)
    if (preset) {
      targetApi.clear()
      applyPresetPlacements(targetApi, preset.placements)
      presetRef.current = presetId
    } else {
      const saved = loadUserPresets(window.localStorage)[presetId]
      if (!saved) return
      try {
        targetApi.clear()
        targetApi.fromJSON(saved)
        presetRef.current = `custom:${presetId}`
      } catch {
        resetToDefault(targetApi, `preset "${presetId}" was unreadable`)
      }
    }
    saveLayout(window.localStorage, targetApi.toJSON(), presetRef.current)
  }

  function savePresetAs() {
    const target = apiRef.current
    if (!target) return
    // prompt() is the pragmatic v1; the palette itself is keyboard-complete.
    const name = window.prompt('Preset name (letters, digits, space, - _)')?.trim()
    if (!name) return
    if (!saveUserPreset(window.localStorage, name, target.toJSON())) {
      setNotice(`could not save preset "${name}" (invalid name or storage full)`)
      return
    }
    presetRef.current = `custom:${name}`
    setUserPresets(Object.keys(loadUserPresets(window.localStorage)))
    saveLayout(window.localStorage, target.toJSON(), presetRef.current)
  }

  const paletteCtx = {
    applyPreset: (id) => apiRef.current && applyPresetByName(apiRef.current, id),
    savePresetAs,
    userPresets,
  }

  // R64: the sidebar's panel rows call this. One source of truth for "show":
  // the palette command itself, so the sidebar cannot grow a second placement
  // policy (floating-reference guard included). An open panel just focuses.
  function showPanel(id) {
    const target = apiRef.current
    if (!target) return
    const open = target.getPanel(id)
    if (open) {
      open.api.setActive()
      return
    }
    runCommand(`show:${id}`, target, paletteCtx)
  }

  const shell = {
    sidebar,
    fileWs,
    onAsk,
    showPanel,
    sessionId,
    prompt,
    pending,
    chat,
    onRefreshArtifacts,
    // P2: store-backed panels + the wiring the new panels need. The footer's
    // processes live in `footer` (App's own poll), not the shell — the
    // Processes panel reads the store.
    store,
    workdir,
    activePath: fileWs.active?.path || '',
  }

  function onDockReady(event) {
    const dockApi = event.api
    apiRef.current = dockApi
    setApi(dockApi)

    // REQ-2/REQ-8: restore the saved arrangement, degrading to the default
    // preset — with a surfaced reason — whenever it cannot be trusted.
    saverRef.current = createDebouncedSaver(() => {
      if (!apiRef.current) return
      saveLayout(window.localStorage, apiRef.current.toJSON(), presetRef.current)
    }, SAVE_DEBOUNCE_MS)

    const saved = loadSavedLayout(window.localStorage, isKnownPanel)
    if (saved.ok) {
      try {
        dockApi.fromJSON(saved.layout)
        presetRef.current = saved.preset
        if (saved.dropped.length > 0) {
          setNotice(`layout restored (dropped panels no longer shipped: ${saved.dropped.join(', ')})`)
        }
      } catch {
        resetToDefault(dockApi, 'saved layout was unreadable')
      }
    } else {
      // A layout that cannot be restored is also cleared from storage, so the
      // notice surfaces once — not again on every boot against the same bad
      // blob. ('missing' is the ordinary first run: silent, nothing to clear.)
      if (saved.reason !== 'missing') clearSavedLayout(window.localStorage)
      const reasons = {
        corrupt: 'saved layout was corrupt',
        version: 'saved layout was from a different version',
        empty: 'no known panels remained',
      }
      resetToDefault(dockApi, reasons[saved.reason] ?? null)
    }

    // Debounced persistence rides dockview's own change event — every drag,
    // close, resize and palette mutation funnels through it.
    dockApi.onDidLayoutChange(() => saverRef.current?.schedule())

    // R59 P4: a popout the browser refused (usually a popup blocker) must not
    // look like the command silently did nothing.
    dockApi.onDidOpenPopoutWindowFail((f) => {
      setNotice(`could not open popout window (${f.reason} — popup blocker?)`)
    })
  }

  return (
    <WorkspaceContext.Provider value={shell}>
      <div data-workspace="dock" className="flex h-screen flex-col bg-neutral-900 text-neutral-200">
        {error && <div className="shrink-0 bg-danger/15 px-4 py-1 text-xs text-danger">{error}</div>}
        <AgentStrip {...agentStrip} />
        {notice && (
          <button
            data-layout-notice
            className="shrink-0 bg-warning/15 px-4 py-1 text-left text-xs text-warning"
            onClick={() => setNotice(null)}
            title="click to dismiss"
          >
            {notice}
          </button>
        )}
        <div className="min-h-0 flex-1">
          <DockviewReact
            theme={themeDark}
            components={COMPONENTS}
            watermarkComponent={(props) => <Watermark {...props} onPreset={applyPresetByName} />}
            onReady={onDockReady}
          />
        </div>
        <CommandPalette api={api} ctx={paletteCtx} />
        <StatusFooter {...footer} />
      </div>
    </WorkspaceContext.Provider>
  )
}
