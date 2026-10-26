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
// along with this program.  <https://www.gnu.org/licenses/>.
// R59 P3 (tech design #1 §4.4): persisted layouts. Pure logic only — the
// storage is injected so tests never need a browser localStorage
// (Workspace.jsx uses window.localStorage directly at its call sites). Workspace.jsx owns the try/catch around `fromJSON`;
// everything here either returns a decision or throws nothing.
//
// The saved shape is:
//   cd-layout-v1        { v, preset, layout: dockview toJSON() }
//   cd-layout-presets-v1 { "name": layout, ... }   (user-saved presets)
//
// Load is defensive by contract (REQ-8): a corrupt, future-versioned or
// partially-unknown layout must degrade — strip what the catalogue no longer
// knows and keep the rest — and only fall back to the default preset when
// nothing usable remains.
// The catalogue's PRESETS are the source of truth for shipped preset ids
// (used by the reserved-name guard below).
import { PRESETS } from './catalogue'

export const LAYOUT_KEY = 'cd-layout-v1'
export const PRESETS_KEY = 'cd-layout-presets-v1'
export const LAYOUT_VERSION = 1

/** The subset of the web Storage interface this module needs. */
export interface KVStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

/** Loose structural types: dockview's serialized shape is internal, so we
 * validate rather than assume. Nothing outside this module reads these
 * fields directly. */
export type SerializedViews = { id?: unknown; views?: unknown; activeView?: unknown }
export type SerializedNode = {
  type?: unknown
  data?: unknown
  size?: unknown
  visible?: unknown
}
export type SerializedLayout = Record<string, unknown> & {
  grid?: { root?: SerializedNode }
  panels?: Record<string, unknown>
}

export interface SavedLayout {
  v: number
  preset: string
  layout: SerializedLayout
}

export type LoadResult =
  | { ok: true; preset: string; layout: SerializedLayout; dropped: string[] }
  /** `reason` is surfaced to the user ("layout reset (…)"), never swallowed. */
  | { ok: false; reason: 'missing' | 'corrupt' | 'version' | 'empty' }

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

// ---------------------------------------------------------------------------
// Unknown-panel stripping
// ---------------------------------------------------------------------------

/**
 * Removes every panel id the catalogue no longer knows from a serialized
 * layout, in place: the `panels` record, every group's `views` list (grid,
 * floating and popout), and any `activeView` left dangling.
 *
 * Returns the ids that were dropped (for the reset notice) or null when the
 * node is malformed — the caller treats malformed the same as corrupt JSON.
 */
export function stripUnknownPanels(
  layout: SerializedLayout,
  isKnown: (id: string) => boolean,
): string[] | null {
  const dropped = new Set<string>()

  const stripViews = (views: unknown): unknown => {
    if (!Array.isArray(views)) return views
    return views.filter((id) => {
      if (typeof id !== 'string' || isKnown(id)) return true
      dropped.add(id)
      return false
    })
  }

  const fixActive = (group: unknown): void => {
    if (!isRecord(group)) return
    group.views = stripViews(group.views)
    const active = group.activeView
    if (typeof active === 'string' && dropped.has(active)) delete group.activeView
  }

  const walkNode = (node: unknown): boolean => {
    if (!isRecord(node)) return false
    if (node.type === 'branch') {
      if (!Array.isArray(node.data)) return false
      return node.data.every(walkNode)
    }
    if (node.type === 'leaf') {
      if (!isRecord(node.data)) return false
      fixActive(node.data)
      return true
    }
    return false
  }

  const panels = layout.panels
  if (isRecord(panels)) {
    for (const id of Object.keys(panels)) {
      if (!isKnown(id)) {
        dropped.add(id)
        delete panels[id]
      }
    }
  }

  const root = layout.grid && isRecord(layout.grid) ? layout.grid.root : undefined
  if (!root || !walkNode(root)) return null

  const windows = [layout.floatingGroups, layout.popoutGroups]
  for (const list of windows) {
    if (!Array.isArray(list)) continue
    for (const win of list) {
      if (!isRecord(win)) continue
      if (isRecord(win.data)) fixActive(win.data)
      const grid = isRecord(win.grid) ? win.grid : undefined
      if (grid) {
        if (!walkNode(grid.root)) return null
        if (isRecord(grid.root) && grid.root.type === 'leaf' && isRecord(grid.root.data)) {
          fixActive(grid.root.data)
        }
      }
    }
  }
  return [...dropped]
}

/** The panel ids a stripped layout still refers to. */
export function panelIds(layout: SerializedLayout): string[] {
  const found = new Set<string>()
  const collect = (views: unknown): void => {
    if (Array.isArray(views)) {
      for (const id of views) if (typeof id === 'string') found.add(id)
    }
  }
  const walkNode = (node: unknown): void => {
    if (!isRecord(node)) return
    if (node.type === 'branch' && Array.isArray(node.data)) node.data.forEach(walkNode)
    if (node.type === 'leaf' && isRecord(node.data)) collect(node.data.views)
  }
  walkNode(layout.grid && isRecord(layout.grid) ? layout.grid.root : undefined)
  for (const list of [layout.floatingGroups, layout.popoutGroups]) {
    if (!Array.isArray(list)) continue
    for (const win of list) {
      if (!isRecord(win)) continue
      if (isRecord(win.data)) collect(win.data.views)
      if (isRecord(win.grid)) walkNode(win.grid.root)
    }
  }
  return [...found]
}

// ---------------------------------------------------------------------------
// Load / save
// ---------------------------------------------------------------------------

function parseSaved(raw: string | null, isKnown: (id: string) => boolean): LoadResult {
  // `clearSavedLayout` stores '' (the KVStorage seam has no removeItem) — an
  // intentional reset must read as "nothing saved" (silent default), not
  // "corrupt" (which would surface a false reset notice).
  if (raw === null || raw === '') return { ok: false, reason: 'missing' }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { ok: false, reason: 'corrupt' }
  }
  if (!isRecord(parsed) || !isRecord(parsed.layout)) return { ok: false, reason: 'corrupt' }
  const v = parsed.v
  if (v !== LAYOUT_VERSION) return { ok: false, reason: 'version' }
  const layout = parsed.layout as SerializedLayout
  const dropped = stripUnknownPanels(layout, isKnown)
  if (dropped === null) return { ok: false, reason: 'corrupt' }
  if (panelIds(layout).length === 0) return { ok: false, reason: 'empty' }
  return {
    ok: true,
    preset: typeof parsed.preset === 'string' ? parsed.preset : 'custom',
    layout,
    dropped,
  }
}

export function loadSavedLayout(
  storage: KVStorage,
  isKnown: (id: string) => boolean,
): LoadResult {
  try {
    return parseSaved(storage.getItem(LAYOUT_KEY), isKnown)
  } catch {
    // localStorage itself can throw (quota, privacy mode) — a broken store
    // must degrade to the default preset, not a blank screen.
    return { ok: false, reason: 'corrupt' }
  }
}

export function saveLayout(
  storage: KVStorage,
  layout: SerializedLayout,
  preset: string,
): boolean {
  try {
    const saved: SavedLayout = { v: LAYOUT_VERSION, preset, layout }
    storage.setItem(LAYOUT_KEY, JSON.stringify(saved))
    return true
  } catch {
    return false // quota/privacy — best effort, never fatal
  }
}

export function clearSavedLayout(storage: KVStorage): void {
  try {
    storage.setItem(LAYOUT_KEY, '')
  } catch {
    /* best effort */
  }
}

// ---------------------------------------------------------------------------
// User presets
// ---------------------------------------------------------------------------

const NAME_RE = /^[\w][\w -]{0,31}$/

// A user preset name that collides with a shipped preset id (or the palette's
// reserved "save-as" verb) would emit a duplicate `preset:<name>` command id
// and leave the user's preset unreachable — `presetById` wins on apply.
const RESERVED_PRESET_NAMES = new Set<string>([...PRESETS.map((p) => p.id), 'save-as'])

export function presetNameValid(name: string): boolean {
  return NAME_RE.test(name) && !RESERVED_PRESET_NAMES.has(name)
}

export function loadUserPresets(storage: KVStorage): Record<string, SerializedLayout> {
  // Null prototype: a stored "__proto__" key (the name guard lets it through —
  // NAME_RE matches it) must not hit Object.prototype's setter when
  // saveUserPreset assigns, which would silently drop the preset.
  const dict = Object.create(null) as Record<string, SerializedLayout>
  try {
    const parsed = JSON.parse(storage.getItem(PRESETS_KEY) ?? '{}')
    if (!isRecord(parsed)) return dict
    for (const [k, v] of Object.entries(parsed)) dict[k] = v
    return dict
  } catch {
    return dict
  }
}

export function saveUserPreset(storage: KVStorage, name: string, layout: SerializedLayout): boolean {
  if (!presetNameValid(name)) return false
  const all = loadUserPresets(storage)
  all[name] = layout
  try {
    storage.setItem(PRESETS_KEY, JSON.stringify(all))
    return true
  } catch {
    return false
  }
}

export function deleteUserPreset(storage: KVStorage, name: string): void {
  const all = loadUserPresets(storage)
  delete all[name]
  try {
    storage.setItem(PRESETS_KEY, JSON.stringify(all))
  } catch {
    /* best effort */
  }
}

// ---------------------------------------------------------------------------
// Debounced save
// ---------------------------------------------------------------------------

/**
 * Coalesces a burst of layout-change events into one write. Returns a
 * controller so the shell can cancel the pending write when it is about to
 * replace the layout itself (preset apply / reset) — without that, the stale
 * pre-apply snapshot would land after the apply and resurrect it.
 */
export function createDebouncedSaver(
  save: () => void,
  ms: number,
  timer: { setTimeout: (fn: () => void, ms: number) => unknown; clearTimeout: (h: unknown) => void } = {
    // Wrapped, not passed bare: `setTimeout` detached from `window` throws
    // "Illegal invocation" in the browser.
    setTimeout: (fn, delay) => setTimeout(fn, delay),
    clearTimeout: (h) => clearTimeout(h),
  },
) {
  let handle: ReturnType<typeof timer.setTimeout> | null = null
  return {
    schedule(): void {
      if (handle !== null) timer.clearTimeout(handle)
      handle = timer.setTimeout(() => {
        handle = null
        save()
      }, ms)
    },
    cancel(): void {
      if (handle !== null) {
        timer.clearTimeout(handle)
        handle = null
      }
    },
    pending(): boolean {
      return handle !== null
    },
  }
}
