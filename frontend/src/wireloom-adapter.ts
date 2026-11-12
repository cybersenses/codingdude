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
// R87 #329 (tech design #4): wireloom-adapter — the v1-pack → Wireloom-source
// compiler and the async render wrapper. compileScreen is TOTAL (never
// throws; preserves the #314 tolerant-parse contract at the render seam);
// the actual SVG comes from wireloom's own renderer, so the pixels stop
// being hand-rolled Sketch glyphs. Grammar facts (bare containers take no
// colon; annotation is a window SIBLING; col <px>|fill) were probed against
// the installed 0.7.0, not assumed.
import type { WireframeRegion, WireframeScreen, WireframeVm } from './wireframes'

// fr→px heuristic from the design: fr weights cannot be expressed (ColWidth
// is px|fill by construction), so proportions map onto a fixed content
// width; the last column stays `fill` to absorb rounding.
const CONTENT_WIDTH = 720

type ProblemSink = string[]

interface Rect { top: number; left: number }

const esc = (s: string): string =>
  s.replace(/\\/g, '').replace(/"/g, "'").replace(/\r?\n/g, ' ').trim()

// Notes carry line breaks that are CONTENT (the design maps them to
// wireloom's `\n` annotation escape), so this variant keeps them.
const escMulti = (s: string): string =>
  s.replace(/\\/g, '').replace(/"/g, "'").replace(/\r?\n/g, '\\n').trim()

const idOf = (screenId: string, name: string): string =>
  `wf-${screenId.replace(/[^a-zA-Z0-9_-]/g, '')}-${name.replace(/[^a-zA-Z0-9_-]/g, '')}`

// The grid-template-areas matrix — area name → {top, left} of its rectangle.
// v1 packs keep each area rectangular, so the first cell suffices to place it.
function areaPositions(template: string): Map<string, Rect> {
  const rows = template.match(/"[^"]*"/g)
  if (!rows || rows.length === 0) return new Map()
  const pos = new Map<string, Rect>()
  rows.forEach((row, top) => {
    row.replace(/"/g, '').trim().split(/\s+/).forEach((name, left) => {
      if (name && name !== '.' && !pos.has(name)) pos.set(name, { top, left })
    })
  })
  return pos
}

// Region content: one mapped child per widget kind. Every branch emits at
// least one child so the wrapping section can always take its colon.
function regionChildren(r: WireframeRegion): string[] {
  const label = esc(r.label) || esc(r.name) || '·'
  switch (r.widget) {
    case 'header':
      // wireloom `header` is window-level chrome — illegal inside a section,
      // so a header region compiles to its bold large-title text instead.
      return [`text "${label}" bold size=large`]
    case 'nav':
      return ['list:', `  slot "${label}" chevron`, '  slot "·"', '  slot "·"']
    case 'form':
      return [`input placeholder="${label}"`, 'input placeholder=""', `button "${label}" primary`]
    case 'table':
      // R87 #330 visual gate: a 3-col grid (≈288px) was the widest band in
      // narrow layouts and read as clipped at the window border; 2×3 stays
      // a believable data grid without dominating the canvas.
      return ['grid cols=2 rows=3:', ...Array.from({ length: 6 }, () => '  cell "·"')]
    case 'list':
      return ['list:', `  slot "${label}"`, '  slot "·"', '  slot "·"']
    case 'chart':
      return ['chart']
    case 'actions':
      return ['row justify=end:', `  button "Cancel"`, `  button "${label}" primary`]
    case 'tabs':
      return ['tabs:', `  tab "${label}"`, '  tab "·"']
    case 'image':
      return ['image']
    case 'code':
      return [`text "${label}" bold`, 'text "······" muted', 'text "········" muted', 'text "·······" muted']
    case 'placeholder':
      return [`slot "${label}"`]
    case 'text':
      // R87 #330 visual gate: the section eyebrow already carries the label,
      // so repeating it as body text read as duplication — the body is the
      // notes line when authored, else muted placeholder dots.
      return r.notes
        ? [`text "${esc(r.notes)}" muted`]
        : ['text "······" muted', 'text "·····" muted']
    default:
      return [`slot "${label}"`]
  }
}

function compileRegion(r: WireframeRegion, screenId: string, indent: string): string[] {
  const lines: string[] = []
  const label = esc(r.label) || esc(r.name) || '·'
  const id = idOf(screenId, r.name || 'region')
  lines.push(`${indent}section "${label}" id="${id}":`)
  for (const child of regionChildren(r)) lines.push(`${indent}  ${child}`)
  return lines
}

// Layout: framed screens become row bands (one per template row, regions
// placed by their rectangle's top-left); template-less screens stack their
// sections. Column widths: equal/absent → fill, authored proportions → px
// with the last column as fill.
function compileBands(s: WireframeScreen, indent: string): { body: string[]; annotations: string[] } {
  const pos = areaPositions(s.template)
  const bands = new Map<number, WireframeRegion[]>()
  const loose: WireframeRegion[] = []
  for (const r of s.regions) {
    const p = r.name ? pos.get(r.name) : undefined
    if (!p) { loose.push(r); continue }
    if (!bands.has(p.top)) bands.set(p.top, [])
    bands.get(p.top)!.push(r)
  }
  const body: string[] = []
  const annotations: string[] = []
  const emitAnnotation = (r: WireframeRegion): void => {
    if (r.notes) annotations.push(`annotation "${escMulti(r.notes)}" target="${idOf(s.id, r.name || 'region')}" position=right`)
  }
  const tops = [...bands.keys()].sort((a, b) => a - b)
  for (const top of tops) {
    const band = [...bands.get(top)!].sort((a, b) => pos.get(a.name)!.left - pos.get(b.name)!.left)
    body.push(`${indent}row:`)
    band.forEach((r, i) => {
      const last = i === band.length - 1
      const weights = s.columns
      const equalOrAbsent = !weights
        || band.every((x) => (weights[pos.get(x.name)!.left] ?? 1) === 1)
      const width = weights
        ? Math.round((weights[pos.get(r.name)!.left] ?? 1) / weights.reduce((a, b) => a + b, 0) * CONTENT_WIDTH)
        : 0
      const sized = equalOrAbsent || last || width <= 0 ? 'col fill:' : `col ${width}:`
      body.push(`${indent}  ${sized}`)
      body.push(...compileRegion(r, s.id, `${indent}    `))
      emitAnnotation(r)
    })
  }
  for (const r of loose) {
    body.push(...compileRegion(r, s.id, indent))
    emitAnnotation(r)
  }
  return { body, annotations }
}

/**
 * Compile one parsed screen into Wireloom source. Total: accepts any
 * parse-valid WireframeScreen and never throws; unknown widgets degrade to
 * slots. Returns the source and pushes nothing onto problems itself —
 * callers own the problems line.
 */
export function compileScreen(s: WireframeScreen, _problems: ProblemSink): string {
  const title = esc(s.title) || esc(s.id)
  const head = `window "${title}":`
  if (s.regions.length === 0) return `${head}\n  text "·"\n`
  const body: string[] = []
  const annotations: string[] = []
  if (s.template) {
    const compiled = compileBands(s, '  ')
    body.push(...compiled.body)
    annotations.push(...compiled.annotations)
  } else {
    for (const r of s.regions) {
      body.push(...compileRegion(r, s.id, '  '))
      if (r.notes) annotations.push(`annotation "${escMulti(r.notes)}" target="${idOf(s.id, r.name || 'region')}" position=right`)
    }
  }
  return [head, ...body, ...annotations].join('\n') + '\n'
}

export interface RenderOutcome {
  svg: string | null
  problem: string | null
}

export interface PackRender {
  svgById: Record<string, string>
  problems: string[]
}

/**
 * Compile + render every screen of a parsed pack. The pack-level seam the
 * view consumes (one effect + one state on the component side): screen svgs
 * come back keyed by screen id; failures become problem lines, never throws.
 * `isStale` lets the caller discard a superseded payload's late resolve
 * (revision loop); `idBase` scopes the render-element ids per artifact so
 * two mounted packs can't collide on svg internal ids.
 */
export async function renderPackScreens(
  vm: Pick<WireframeVm, 'screens'>,
  theme: 'default' | 'dark',
  isStale: () => boolean = () => false,
  idBase = 'wf',
): Promise<PackRender> {
  const svgById: Record<string, string> = {}
  const problems: string[] = []
  const base = idBase.replace(/[^a-zA-Z0-9_-]/g, '') || 'wf'
  for (const s of vm.screens) {
    if (isStale()) break
    const source = compileScreen(s, problems)
    const out = await renderScreen(`${base}-${s.id}`, source, theme)
    if (isStale()) break
    if (out.svg) svgById[s.id] = out.svg
    else problems.push(`${s.id}: ${out.problem ?? 'render failed'}`)
  }
  return { svgById, problems }
}

/**
 * Render compiled source through wireloom. Async by the library's contract
 * (render returns a Promise); a WireloomError becomes a problem string, not
 * an exception — the view stays crash-free at this seam. The dynamic import
 * keeps wireloom out of the main chunk (~30 kB gz).
 */
export async function renderScreen(
  id: string,
  source: string,
  theme: 'default' | 'dark',
): Promise<RenderOutcome> {
  try {
    const wireloom = await import('wireloom')
    const r = await wireloom.render(id, source, { theme })
    return { svg: r.svg, problem: null }
  } catch (e) {
    const msg = e instanceof Error ? e.message.split('\n')[0] : String(e)
    return { svg: null, problem: `render failed: ${msg}` }
  }
}
