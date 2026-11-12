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
// R85 #314: defensive parse seam for wireframe packs — the WireframeView
// renderer's whole input contract. Mirrors artifacts.ts: framework-free,
// unit-tested under vitest, never throws. The backend validates structure at
// emit time; this seam only guarantees the renderer cannot crash on whatever
// an old artifact or a hand edit actually contains.
export interface WireframeRegion {
  name: string
  widget: string
  label: string
  notes: string
}

export interface WireframeScreen {
  id: string
  title: string
  /** CSS grid-template-areas value ('"nav header" ...'); '' → stack regions. */
  template: string
  /**
   * R87-A: authored track weights (all positive numbers). Length must match
   * the template's track count — set at parse time or dropped with a problem.
   * Absent → the renderer splits tracks equally.
   */
  columns?: number[]
  rows?: number[]
  regions: WireframeRegion[]
}

export interface WireframeFlow {
  from: string
  to: string
  trigger: string
  label: string
}

export interface WireframeVm {
  /** True iff the pack is DSL v1 — screens are suppressed otherwise. */
  ok: boolean
  screens: WireframeScreen[]
  flows: WireframeFlow[]
  /** Human-readable anomalies the renderer surfaces as a warning line. */
  problems: string[]
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '')

// R87-A: an authored weights list is a non-empty array of positive finite
// numbers. Anything else (wrong values, wrong length handled at track time)
// is rejected so a mangled payload degrades, never crashes.
function isWeights(v: unknown): v is number[] {
  return Array.isArray(v) && v.length > 0
    && v.every((n) => typeof n === 'number' && Number.isFinite(n) && n > 0)
}

// R87-A: keep valid authored weights on the screen; drop present-but-invalid
// ones with a problem line (tolerant parse, #314 contract). Absent stays
// absent — undefined means "not authored", not "empty".
function weightsOr(v: unknown, field: string, id: string, problems: string[]): number[] | undefined {
  if (v === undefined || v === null) return undefined
  if (isWeights(v)) return v
  problems.push(`dropped invalid ${field} for screen '${id}'`)
  return undefined
}

function parseScreen(raw: unknown, problems: string[]): WireframeScreen | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  const s = raw as Record<string, unknown>
  const regions: WireframeRegion[] = []
  if (Array.isArray(s.regions)) {
    for (const r of s.regions) {
      if (r === null || typeof r !== 'object' || Array.isArray(r)) continue
      const ro = r as Record<string, unknown>
      regions.push({ name: str(ro.name), widget: str(ro.widget), label: str(ro.label), notes: str(ro.notes) })
    }
  }
  const id = str(s.id)
  if (!id) {
    // #320: the warning used to claim a drop while the screen was still
    // rendered with id:'' (duplicate-key risk). Drop for real — flows are
    // dropped the same way, and layoutScreens already filters empty ids.
    problems.push('dropped a screen with no id')
    return null
  }
  const columns = weightsOr(s.columns, 'columns', id, problems)
  const rows = weightsOr(s.rows, 'rows', id, problems)
  return {
    id,
    title: str(s.title),
    template: str(s.template),
    ...(columns !== undefined ? { columns } : {}),
    ...(rows !== undefined ? { rows } : {}),
    regions,
  }
}

function parseFlow(raw: unknown): WireframeFlow | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  const f = raw as Record<string, unknown>
  if (!str(f.from) || !str(f.to)) return null
  return { from: str(f.from), to: str(f.to), trigger: str(f.trigger), label: str(f.label) }
}

export function parseWireframe(payload: unknown): WireframeVm {  const problems: string[] = []
  const vm: WireframeVm = { ok: false, screens: [], flows: [], problems }
  const pack = payload !== null && typeof payload === 'object' && !Array.isArray(payload)
    ? (payload as Record<string, unknown>)
    : null
  if (pack === null) {
    problems.push('wireframe payload is not an object')
    return vm
  }
  if (pack.version !== 1) {
    problems.push(`unsupported wireframe version (${String(pack.version)}) — ask the agent to re-emit`)
    return vm
  }
  vm.ok = true
  if (Array.isArray(pack.screens)) {
    for (const raw of pack.screens) {
      const s = parseScreen(raw, problems)
      if (s) vm.screens.push(s)
    }
  }
  if (vm.screens.length === 0) problems.push('no usable screens in pack')
  if (Array.isArray(pack.flows)) {
    for (const raw of pack.flows) {
      const f = parseFlow(raw)
      if (f) vm.flows.push(f)
      else problems.push('dropped a malformed flow entry')
    }
  }
  return vm
}

// R85 #316: click-to-focus toggle table — pure so it specs independently of
// the DOM (re-click clears, other screen moves).
export function applyFocus(current: string | null, screenId: string | null): string | null {
  return current === screenId ? null : screenId
}

// R87-A (#323): grid track sizes for a screen. Authored weights become fr
// tracks; anything absent or invalid falls back to an equal split across the
// template's own track count (a wrong *count* is reported as a problem, a
// merely-absent list is the normal v1-pack path and stays silent).
export interface ScreenTracks {
  columns: string
  rows: string
}

function templateShape(template: string): { cols: number; rows: number } | null {
  const quoted = template.match(/"[^"]*"/g)
  if (quoted && quoted.length > 0) {
    const cols = quoted[0].replace(/"/g, '').trim().split(/\s+/).filter((t) => t && t !== '.').length
    return { cols, rows: quoted.length }
  }
  const oneRow = template.trim().split(/\s+/).filter((t) => t && t !== '.')
  return oneRow.length === 0 ? null : { cols: oneRow.length, rows: 1 }
}

const equalTracks = (n: number) => Array.from({ length: n }, () => '1fr').join(' ')

function trackList(weights: unknown, count: number, field: string, problems: string[]): string {
  if (weights === undefined || weights === null) return equalTracks(count)
  if (isWeights(weights) && weights.length === count) return weights.map((n) => `${n}fr`).join(' ')
  problems.push(`dropped invalid ${field} (expected ${count} weights) — using equal split`)
  return equalTracks(count)
}

export function screenTracks(
  screen: Pick<WireframeScreen, 'template' | 'columns' | 'rows'>,
  problems: string[] = [],
): ScreenTracks {
  const shape = templateShape(screen.template)
  if (!shape) return { columns: '', rows: '' }
  return {
    columns: trackList(screen.columns, shape.cols, 'columns', problems),
    rows: trackList(screen.rows, shape.rows, 'rows', problems),
  }
}

// R85 #316 (REQ-4): layered layout for the SVG node-link flow map.
// Longest-path layering over flows; cycles are capped by the relaxation
// budget so they can never hang; screens keep input order inside a layer.
export interface FlowMapPos {
  x: number
  y: number
}

export interface FlowLayout {
  /** Screen ids grouped by layer, layers ordered shallow → deep. */
  layers: string[][]
  /** Grid position per screen id (layer column, row within its layer). */
  pos: Record<string, FlowMapPos>
}

export const FLOW_MAP_GRID = { colW: 170, rowH: 44 }

export function layoutScreens(
  screens: { id: string }[],
  flows: { from: string; to: string }[],
): FlowLayout {
  const ids = screens.map((s) => s.id).filter((id) => typeof id === 'string' && id !== '')
  const depth = new Map(ids.map((id) => [id, 0]))
  const incoming = new Map(ids.map((id) => [id, [] as string[]]))
  for (const f of flows) {
    if (depth.has(f.from) && depth.has(f.to)) incoming.get(f.to)!.push(f.from)
  }
  const order = new Map(ids.map((id, i) => [id, i])) // input order, for layer rows
  for (let round = 0; round <= ids.length; round++) {
    let changed = false
    for (const id of ids) {
      const ps = incoming.get(id)!
      if (ps.length === 0) continue
      const d = Math.max(...ps.map((p) => depth.get(p)!)) + 1
      if (d !== depth.get(id) && d <= ids.length) {
        depth.set(id, d)
        changed = true
      }
    }
    if (!changed) break
  }
  const byDepth = new Map<number, string[]>()
  for (const id of ids) {
    const d = depth.get(id)!
    if (!byDepth.has(d)) byDepth.set(d, [])
    byDepth.get(d)!.push(id)
  }
  const layers: string[][] = []
  const pos: Record<string, FlowMapPos> = {}
  for (const d of [...byDepth.keys()].sort((a, b) => a - b)) {
    const row = byDepth.get(d)!.sort((a, b) => order.get(a)! - order.get(b)!)
    layers.push(row)
    row.forEach((id, i) => {
      pos[id] = { x: d * FLOW_MAP_GRID.colW, y: i * FLOW_MAP_GRID.rowH }
    })
  }
  return { layers, pos }
}
