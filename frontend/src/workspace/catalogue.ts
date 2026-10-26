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
// R59 P1 (/docs/tech-design #1): the single source of truth for *what* can be
// on screen and *how the first boot arranges it*. The palette (P3), presets
// (P3) and saved-layout validation (P3) all read this file rather than
// carrying their own copy of the panel list.
//
// Scope note: every catalogue entry has a registered component — a spec with
// no component would be a panel the UI offers and then fails to render
// (enforced by catalogue.test.ts against the Workspace registry list).
import { PANE_SPECS } from '../panes'

export type PanelId = 'nav' | 'explorer' | 'editor' | 'chat' | 'diff' | 'graph'
  | 'planning' | 'artifacts' | 'notes' | 'renders' | 'terminal' | 'output'
  | 'waterfall' | 'trace' | 'cost' | 'memory' | 'mcp' | 'config' | 'standards'
  | 'processes'

export interface PanelSpec {
  /** Stable id: persisted in saved layouts (P3) and used as the dockview panel id. */
  id: PanelId
  title: string
  /** dockview component registration name (see Workspace.jsx `components`). */
  component: string
  /**
   * `always` keeps the panel's DOM alive while it is hidden. Required for
   * stateful/iframe content — dockview moves the DOM node between groups on a
   * drag, and re-parenting an iframe reloads it.
   */
  renderer?: 'always'
  minWidth?: number
  minHeight?: number
}

// Order is the palette order (P3).
export const PANELS: readonly PanelSpec[] = [
  { id: 'nav', title: 'Projects & sessions', component: 'nav', minWidth: PANE_SPECS.sidebar.min },
  { id: 'explorer', title: 'Explorer', component: 'explorer', minWidth: PANE_SPECS.rail.min },
  // Monaco restores its own scroll/undo from the model, but keeping the node
  // alive avoids a re-mount flash on every move (REQ-4).
  { id: 'editor', title: 'Editor', component: 'editor', renderer: 'always' },
  // Prompt draft + streaming transcript + scroll position must survive a move.
  { id: 'chat', title: 'Chat', component: 'chat', renderer: 'always', minWidth: PANE_SPECS.right.min },
  { id: 'diff', title: 'Diff', component: 'diff', minHeight: PANE_SPECS.dock.min },
  // R59 P2: the remaining dock tabs, all closable-but-not-in-the-default-
  // preset; they are opened on demand from the command palette (P3), not on
  // boot. renderer:'always' marks stateful/iframe panels whose DOM must
  // survive being hidden (tech design §3, §4.1).
  { id: 'graph', title: 'Graph', component: 'graph' },
  { id: 'planning', title: 'Planning', component: 'planning' },
  { id: 'artifacts', title: 'Artifacts', component: 'artifacts', renderer: 'always' },
  { id: 'notes', title: 'Notes', component: 'notes' },
  { id: 'renders', title: 'Renders', component: 'renders', renderer: 'always' },
  { id: 'terminal', title: 'Terminal', component: 'terminal', renderer: 'always' },
  { id: 'output', title: 'Output', component: 'output' },
  { id: 'waterfall', title: 'Waterfall', component: 'waterfall' },
  { id: 'trace', title: 'Trace', component: 'trace' },
  { id: 'cost', title: 'Cost', component: 'cost' },
  { id: 'memory', title: 'Memory', component: 'memory' },
  { id: 'mcp', title: 'MCP', component: 'mcp' },
  { id: 'config', title: 'Config', component: 'config', renderer: 'always' },
  { id: 'standards', title: 'Standards', component: 'standards', renderer: 'always' },
  { id: 'processes', title: 'Processes', component: 'processes' },
]

export function panelSpec(id: string): PanelSpec | undefined {
  return PANELS.find((p) => p.id === id)
}

/**
 * The addPanel options every spec contributes (id/component/title/renderer plus
 * the size-clamp minimums). Single source for the palette's `show:` command and
 * the preset placements in Workspace — both previously rebuilt this clump by
 * hand (post-push review: Duplicated Code).
 *
 * `AddPanelOptions` extends `Partial<Constraints>`, so the catalogue's
 * minimums land on dockview's own resize clamp instead of being inert data —
 * without them a docked panel could be dragged below the size the classic
 * layout's PANE_SPECS clamp allows.
 */
export function panelOptions(spec: PanelSpec): Record<string, unknown> {
  return {
    id: spec.id,
    component: spec.component,
    title: spec.title,
    ...(spec.renderer !== undefined ? { renderer: spec.renderer } : {}),
    ...(spec.minWidth !== undefined ? { minimumWidth: spec.minWidth } : {}),
    ...(spec.minHeight !== undefined ? { minimumHeight: spec.minHeight } : {}),
  }
}

export function isKnownPanel(id: string): boolean {
  return panelSpec(id) !== undefined
}

export type PlacementDirection = 'left' | 'right' | 'above' | 'below' | 'within'

export interface Placement {
  id: PanelId
  /** Omitted only for the first placement, which seeds the whole grid. */
  direction?: PlacementDirection
  /** Must name a panel placed *before* this one — see catalogue.test.ts. */
  referencePanel?: PanelId
  initialWidth?: number
  initialHeight?: number
}

// REQ-7: first boot reproduces today's screen, so the sizes are the classic
// layout's own persisted fallbacks rather than new numbers:
//
//   ┌────────┬──────────┬────────────────────┬─────────┐
//   │ nav    │ explorer │ editor             │ chat    │
//   │        │          ├────────────────────┤         │
//   │        │          │ diff               │         │
//   └────────┴──────────┴────────────────────┴─────────┘
//
// Applied in order through the public addPanel API (Workspace.jsx) instead of
// being hand-written as dockview's serialized grid JSON: the serialized form is
// an internal shape we cannot verify from here, and a placement list is both
// readable and testable.
export const DEFAULT_PRESET: readonly Placement[] = [
  { id: 'nav', initialWidth: PANE_SPECS.sidebar.fallback },
  { id: 'explorer', direction: 'right', referencePanel: 'nav', initialWidth: PANE_SPECS.rail.fallback },
  { id: 'editor', direction: 'right', referencePanel: 'explorer' },
  { id: 'chat', direction: 'right', referencePanel: 'editor', initialWidth: PANE_SPECS.right.fallback },
  { id: 'diff', direction: 'below', referencePanel: 'editor', initialHeight: PANE_SPECS.dock.fallback },
]

// R59 P3 (tech design §4.5): the other shipped presets. Every entry follows
// DEFAULT_PRESET's rules — seed first, then references to earlier placements —
// enforced by the preset tests below, because a forward reference throws at
// mount time inside dockview.
export interface NamedPreset {
  id: string
  title: string
  placements: readonly Placement[]
}

export const PRESETS: readonly NamedPreset[] = [
  { id: 'default', title: 'Default', placements: DEFAULT_PRESET },
  {
    id: 'debug',
    title: 'Debug',
    placements: [
      { id: 'nav', initialWidth: PANE_SPECS.sidebar.min },
      { id: 'editor', direction: 'right', referencePanel: 'nav' },
      // Graph + Trace under the editor, Cost stacked below them.
      { id: 'graph', direction: 'below', referencePanel: 'editor' },
      { id: 'trace', direction: 'within', referencePanel: 'graph' },
      { id: 'cost', direction: 'below', referencePanel: 'graph', initialHeight: PANE_SPECS.dock.min },
      { id: 'chat', direction: 'right', referencePanel: 'editor', initialWidth: PANE_SPECS.right.min },
    ],
  },
  {
    id: 'review',
    title: 'Review',
    placements: [
      { id: 'nav', initialWidth: PANE_SPECS.sidebar.min },
      { id: 'editor', direction: 'right', referencePanel: 'nav' },
      // Diff | Waterfall | Output three-up (tech design §4.5).
      { id: 'diff', direction: 'below', referencePanel: 'editor' },
      { id: 'waterfall', direction: 'right', referencePanel: 'diff' },
      { id: 'output', direction: 'right', referencePanel: 'waterfall' },
    ],
  },
  {
    id: 'watching',
    title: 'Watching',
    placements: [
      { id: 'nav', initialWidth: PANE_SPECS.sidebar.min },
      { id: 'chat', direction: 'right', referencePanel: 'nav', initialWidth: PANE_SPECS.right.fallback },
      // Editor + Diff centre, Processes bottom (tech design §4.5).
      { id: 'editor', direction: 'right', referencePanel: 'chat' },
      { id: 'diff', direction: 'below', referencePanel: 'editor' },
      { id: 'processes', direction: 'below', referencePanel: 'diff', initialHeight: PANE_SPECS.dock.min },
    ],
  },
]

export function presetById(id: string): NamedPreset | undefined {
  return PRESETS.find((p) => p.id === id)
}
