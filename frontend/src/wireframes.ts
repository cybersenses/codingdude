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
  if (!id) problems.push('dropped a screen with no id')
  return { id, title: str(s.title), template: str(s.template), regions }
}

function parseFlow(raw: unknown): WireframeFlow | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  const f = raw as Record<string, unknown>
  if (!str(f.from) || !str(f.to)) return null
  return { from: str(f.from), to: str(f.to), trigger: str(f.trigger), label: str(f.label) }
}

export function parseWireframe(payload: unknown): WireframeVm {
  const problems: string[] = []
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
