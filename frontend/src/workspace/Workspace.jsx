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
import React, { createContext, useContext, useEffect, useState } from 'react'
import { DockviewReact, themeDark } from 'dockview-react'
import 'dockview-react/dist/styles/dockview.css'
import { call } from '../api'
import { DEFAULT_PRESET, panelSpec } from './catalogue'
import { Sidebar } from '../chrome/Sidebar.jsx'
import { AgentStrip } from '../chrome/AgentStrip.jsx'
import { StatusFooter } from '../chrome/StatusFooter.jsx'
import { FileTree } from '../panels/Explorer.jsx'
import { EditorPane } from '../panels/Editor.jsx'
import { Chat } from '../panels/Chat.jsx'
import { Prompt } from '../panels/Prompt.jsx'
import { DiffPanel } from '../panels/dock/Diff.jsx'
import { PendingArtifactCard } from '../cards/chatCards.jsx'

// Panel components read their data from this context rather than from dockview
// `params`: params are serialized into the saved layout, so they cannot carry
// callbacks or live state. React portals keep the dock's panels inside this
// tree, so context reaches them wherever they are docked.
//
// P4 caveat: a POPOUT panel is a separate document with its own React root and
// will not see this provider. Popout support must move these bags into a
// module-level store at that point (tech design §4.3/§4.7).
const WorkspaceContext = createContext(null)

function useShell() {
  const shell = useContext(WorkspaceContext)
  if (!shell) throw new Error('workspace panel rendered outside the shell provider')
  return shell
}

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

// The dock's own poll, not DockPanel's: P1 runs both shells side by side, so the
// classic dock keeps its shared poll while this panel fetches what it shows.
// P2 retires both into the visibility-gated store (tech design §4.3).
const DIFF_POLL_MS = 4000

function DiffTabPanel() {
  const { sessionId } = useShell()
  const [data, setData] = useState({ diff: undefined, diffSummary: [], impact: null })
  const [failure, setFailure] = useState(null)

  useEffect(() => {
    if (!sessionId) {
      setData({ diff: undefined, diffSummary: [], impact: null })
      setFailure(null)
      return
    }
    let stop = false
    async function poll() {
      try {
        const r = await call(`/sessions/${sessionId}/diff`)
        if (stop) return
        setData({ diff: r.diff, diffSummary: r.summary || [], impact: r.impact || null })
        setFailure(null)
      } catch (err) {
        // #234: a failed fetch must not look like "no changes yet".
        if (!stop) setFailure(String(err instanceof Error ? err.message : err))
      }
      if (!stop) setTimeout(poll, DIFF_POLL_MS)
    }
    poll()
    return () => { stop = true }
  }, [sessionId])

  if (!sessionId) {
    return (
      <div data-panel="diff" className="p-2 text-xs text-ink-muted">
        Select a session to see diffs, files, cost and trace.
      </div>
    )
  }
  if (failure) {
    return (
      <div data-panel="diff" className="m-2 rounded border border-danger/40 bg-danger/10 p-3 text-xs text-danger">
        could not load this tab: {failure}
      </div>
    )
  }
  return (
    <div data-panel="diff" className="h-full overflow-y-auto p-2">
      <DiffPanel {...data} />
    </div>
  )
}

// Module-level so the registry identity is stable across renders.
const COMPONENTS = {
  nav: NavPanel,
  explorer: ExplorerPanel,
  editor: EditorPanel,
  chat: ChatPanel,
  diff: DiffTabPanel,
}

// ---------------------------------------------------------------------------
// Preset application
// ---------------------------------------------------------------------------

// Builds the default arrangement through the public addPanel API (see the note
// in catalogue.ts on why the preset is placements, not serialized grid JSON).
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
// Shell
// ---------------------------------------------------------------------------

export function Workspace({ error, agentStrip, sidebar, fileWs, onAsk, sessionId, prompt, pending, chat, footer, onRefreshArtifacts }) {
  const shell = { sidebar, fileWs, onAsk, sessionId, prompt, pending, chat, onRefreshArtifacts }
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
            onReady={(event) => applyDefaultPreset(event.api)}
          />
        </div>
        <StatusFooter {...footer} />
      </div>
    </WorkspaceContext.Provider>
  )
}
