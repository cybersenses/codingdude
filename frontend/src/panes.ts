// Single source of truth for resizable-pane geometry: localStorage key,
// min/max clamp, and drag-delta sign convention. Divider drag handlers in
// App.jsx read these so a new pane can't wire to the wrong clamp again (#74).

export interface PaneSpec {
  key: string
  min: number
  max: number
  fallback: number
}

export const PANE_SPECS = {
  sidebar: { key: 'cd-sidebar-w', min: 180, max: 500, fallback: 256 },
  rail: { key: 'cd-rail-w', min: 140, max: 420, fallback: 208 },
  right: { key: 'cd-right-w', min: 280, max: 700, fallback: 384 },
  dock: { key: 'cd-dock-h', min: 120, max: 560, fallback: 240 },
} satisfies Record<string, PaneSpec>

export type PaneName = keyof typeof PANE_SPECS

// sidebar/rail sit left of their content: dragging right grows them.
// right/dock sit at the trailing edge of their space: the delta inverts.
const INVERTED = new Set(['right', 'dock'])

export function paneWidth(which: PaneName, start: number, delta: number): number {
  const spec = PANE_SPECS[which]
  const w = INVERTED.has(which) ? start - delta : start + delta
  return Math.min(spec.max, Math.max(spec.min, w))
}
