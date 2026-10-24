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
// Scope note: only panels that P1 actually ships a component for are listed.
// The remaining fifteen dock tabs are registered here as their components move
// onto the dock in P2 — a spec with no registered component would be a panel
// the UI offers and then fails to render.
import { PANE_SPECS } from '../panes'

export type PanelId = 'nav' | 'explorer' | 'editor' | 'chat' | 'diff'

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
]

export function panelSpec(id: string): PanelSpec | undefined {
  return PANELS.find((p) => p.id === id)
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
