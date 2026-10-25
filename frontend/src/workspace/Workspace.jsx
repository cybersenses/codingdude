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
// R59 P1 (tech design #1 §4.2): the dockable shell, reached with
// `?layout=dock`. The classic flexbox layout in App.jsx stays the default while
// the phases land, so either shell can be compared side by side.
//
// Fixed chrome stays outside the dock — the error banner, AgentStrip and status
// footer describe the shell, not a panel, and every phase keeps them there.
import React, { useEffect, useRef, useState } from 'react'
import { DockviewReact, themeDark } from 'dockview-react'
import 'dockview-react/dist/styles/dockview.css'
import { DEFAULT_PRESET, PANELS, panelSpec } from './catalogue'
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
import { sessionTopics } from '../store/sessionTopics'
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
const store = createSessionStore(sessionTopics)

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------

function NavPanel() {
  const { sidebar } = useShell()
  // The dock owns the width now; Sidebar still wants an explicit one.
  // `data-panel` is what tools/ui_smoke.py asserts on — the tab bar existing is
  // not proof that a panel body rendered.
  return (
    <div data-panel="nav" className="flex h-full min-h-0 flex-col">
      <Sidebar width="100%" {...sidebar} />
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
// Post-push review fix: the flag is synced through a `countedRef` that mirrors
// whether *this* subscriber is currently counted visible. The earlier version
// decremented unconditionally on unmount, which — with two subscribers on one
// topic (Output + Waterfall both read `output`) — subtracted twice and left a
// still-visible sibling unpolled.
function visible(topic, Panel) {
  function GatedPanel(props) {
    const { store: shellStore, sessionId } = useShell()
    const panelApi = props.api
    const countedRef = useRef(true) // subscribe() counted this subscriber visible
    useEffect(() => {
      if (!panelApi || typeof panelApi.onDidVisibilityChange !== 'function') return
      const sync = (isVisible) => {
        if (isVisible === countedRef.current) return
        shellStore.setVisible(topic, sessionId, isVisible)
        countedRef.current = isVisible
      }
      const disp = panelApi.onDidVisibilityChange((ev) => sync(ev.isVisible))
      // Correct the subscribe-time +1 if dockview mounted the panel hidden
      // (a background tab).
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

// Builds the default arrangement through the public addPanel API (see the note
// in catalogue.ts on why the preset is placements, not serialized grid JSON).
//
// addPanel's `initialWidth` alone does not reproduce the classic geometry: the
// new group is created by splitting its reference and the sizes it lands on are
// proportional, which left the editor column ~115px wide with two ~500px
// columns beside it. So the fixed-size columns are pinned explicitly once the
// layout exists; the flexible middle keeps whatever is left.
function applyDefaultPreset(api) {
  for (const placement of DEFAULT_PRESET) {
    const spec = panelSpec(placement.id)
    if (!spec) continue
    api.addPanel({
      id: spec.id,
      component: spec.component,
      title: spec.title,
      renderer: spec.renderer,
      initialWidth: placement.initialWidth,
      initialHeight: placement.initialHeight,
      // `AddPanelOptions` extends `Partial<Constraints>`, so the catalogue's
      // minimums land on dockview's own resize clamp instead of being inert
      // data. Without them a docked panel could be dragged below the size the
      // classic layout's PANE_SPECS clamp allows.
      ...(spec.minWidth !== undefined ? { minimumWidth: spec.minWidth } : {}),
      ...(spec.minHeight !== undefined ? { minimumHeight: spec.minHeight } : {}),
      ...(placement.referencePanel
        ? { position: { direction: placement.direction, referencePanel: placement.referencePanel } }
        : {}),
    })
  }
  // One frame later, so the groups have been laid out and setSize has actual
  // geometry to resize against.
  requestAnimationFrame(() => pinSizes(api))
}

const PINNED_WIDTHS = DEFAULT_PRESET.filter((p) => p.initialWidth !== undefined)
const PINNED_HEIGHTS = DEFAULT_PRESET.filter((p) => p.initialHeight !== undefined)

function pinSizes(api) {
  for (const { id, initialWidth } of PINNED_WIDTHS) {
    api.getPanel(id)?.api.setSize({ width: initialWidth })
  }
  for (const { id, initialHeight } of PINNED_HEIGHTS) {
    api.getPanel(id)?.api.setSize({ height: initialHeight })
  }
}

// Shown when every panel has been closed. REQ-8's escape hatch plus a way back
// to a known-good arrangement once drag-and-drop is in the user's hands.
function Watermark({ containerApi }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-xs text-ink-muted">
      <p>Every panel is closed.</p>
      <button
        className="rounded bg-brand-700 px-3 py-1 text-xs text-brand-fg hover:bg-brand-600"
        onClick={() => {
          containerApi.clear()
          applyDefaultPreset(containerApi)
        }}
      >
        Reset layout
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Panel bar (P2 stopgap for the P3 command palette)
// ---------------------------------------------------------------------------

// The palette is P3; until it lands, closed panels are opened from this bar —
// one button per catalogue entry not currently in the layout. Rebuilt on every
// layout change (open/close/move) so the list never offers an open panel.
function PanelBar({ api }) {
  const [openIds, setOpenIds] = useState([])
  useEffect(() => {
    if (!api) return
    const update = () => setOpenIds(api.panels.map((p) => p.id))
    update()
    const disp = api.onDidLayoutChange(update)
    return () => disp.dispose()
  }, [api])
  const closed = PANELS.filter((p) => !openIds.includes(p.id))
  if (!api || closed.length === 0) return null
  return (
    <div data-panel-bar className="flex flex-wrap gap-1 border-b border-line bg-neutral-900 px-2 py-1">
      {closed.map((spec) => (
        <button
          key={spec.id}
          title={`open the ${spec.title} panel`}
          className="rounded px-2 py-0.5 text-[10px] text-ink-muted hover:bg-surface hover:text-ink"
          onClick={() =>
            api.addPanel({
              id: spec.id,
              component: spec.component,
              title: spec.title,
              renderer: spec.renderer,
              ...(spec.minWidth !== undefined ? { minimumWidth: spec.minWidth } : {}),
              ...(spec.minHeight !== undefined ? { minimumHeight: spec.minHeight } : {}),
              position: { direction: 'within', referencePanel: api.activePanel?.id || 'diff' },
            })
          }
        >
          + {spec.title}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

export function Workspace({ error, agentStrip, sidebar, fileWs, onAsk, sessionId, prompt, pending, chat, footer, onRefreshArtifacts, workdir, reviewDiff = 0 }) {
  const [api, setApi] = useState(null)
  const apiRef = useRef(null)

  // #75's "Review changes →" bumps a counter in App. The classic shell answers
  // it by switching DockPanel to the Diff tab; here it has to activate the
  // `diff` panel instead, or the button silently does nothing in this shell.
  useEffect(() => {
    if (reviewDiff > 0) apiRef.current?.getPanel('diff')?.api.setActive()
  }, [reviewDiff])

  const shell = {
    sidebar,
    fileWs,
    onAsk,
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

  return (
    <WorkspaceContext.Provider value={shell}>
      <div data-workspace="dock" className="flex h-screen flex-col bg-neutral-900 text-neutral-200">
        {error && <div className="shrink-0 bg-danger/15 px-4 py-1 text-xs text-danger">{error}</div>}
        <AgentStrip {...agentStrip} />
        <div className="min-h-0 flex-1">
          <DockviewReact
            theme={themeDark}
            components={COMPONENTS}
            watermarkComponent={Watermark}
            onReady={(event) => {
              apiRef.current = event.api
              setApi(event.api)
              applyDefaultPreset(event.api)
            }}
          />
        </div>
        <PanelBar api={api} />
        <StatusFooter {...footer} />
      </div>
    </WorkspaceContext.Provider>
  )
}
