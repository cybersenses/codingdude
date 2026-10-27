// CodingDude — a personal coding agent.
// Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.
// R69 #261: two entry points, one reveal path. The agent's reveal_code tool
// (live runs) and clickable path:line citations (any message, including
// history) both end as a `cd-open-file` window event carrying
// {path, start, end}; Workspace owns the listener (showPanel + openFile).
//
// Framework-free so every rule here is vitest-coverable — no React imports.

/** A citation like `src/app.py:12`, `panels/Editor.jsx:24-31` (optionally
 * with a drive-letter prefix and a line range). The extension requirement
 * keeps times (`10:30`) and prose (`note: 1`) out. */
export const CITATION_RE = /((?:[A-Za-z]:)?[\w./\\-]+\.[A-Za-z0-9]{1,8}):(\d+)(?:-(\d+))?/g

export interface RevealTarget {
  path: string
  start: number
  end: number
}

/** The in-app link scheme the citation plugin emits; Chat renders these as
 * reveal buttons instead of navigation. */
export const CD_OPEN_SCHEME = 'cdopen://'

/** Clamp to 1-based and swap a reversed range: `9-3` is a typo for `3-9`,
 * not an empty range. ONE normalization for every entry point — tool args
 * (parseRevealArgs) and clicked citations (parseCitationHref → editor) must
 * reveal the same lines for the same citation text. */
export function normalizeRange(start: number, end: number): { start: number; end: number } {
  const s = Math.max(1, Math.floor(start))
  const e = Math.max(1, Math.floor(end))
  return { start: Math.min(s, e), end: Math.max(s, e) }
}

export function citationHref(m: RegExpExecArray): string {
  const [, path, start, end] = m
  // The path is percent-encoded: `new URL` would otherwise eat the first
  // segment as the hostname (`cdopen://src/app.py` -> host 'src').
  return `${CD_OPEN_SCHEME}${encodeURIComponent(path)}?start=${start}&end=${end ?? start}`
}

/** Parse a `cdopen://path?start=&end=` href back into a reveal target
 * (null when malformed — the caller ignores the click). Hand-rolled split
 * instead of `new URL`: with a `//` authority, URL swallows the whole path
 * into an (empty) hostname for opaque schemes like this one. */
export function parseCitationHref(href: string): RevealTarget | null {
  if (!href.startsWith(CD_OPEN_SCHEME)) return null
  const rest = href.slice(CD_OPEN_SCHEME.length)
  const q = rest.indexOf('?')
  const pathPart = q === -1 ? rest : rest.slice(0, q)
  const params = new URLSearchParams(q === -1 ? '' : rest.slice(q + 1))
  let path = ''
  try {
    path = decodeURIComponent(pathPart)
  } catch {
    return null
  }
  const start = Number(params.get('start'))
  const end = Number(params.get('end') ?? params.get('start'))
  if (!path.trim() || !Number.isFinite(start) || !Number.isFinite(end)) return null
  return { path, ...normalizeRange(start, end) }
}

/**
 * TOOL_CALL_START carries the tool args as a JSON *string* (App.jsx keeps
 * `ev.args` verbatim); sub-agent events may already be objects. Malformed
 * input is the agent's problem, not a crash: return null and skip.
 */
export function parseRevealArgs(raw: unknown): RevealTarget | null {
  let args: unknown = raw
  if (typeof raw === 'string') {
    try {
      args = JSON.parse(raw)
    } catch {
      return null
    }
  }
  if (typeof args !== 'object' || args === null) return null
  const a = args as Record<string, unknown>
  if (typeof a.path !== 'string' || a.path === '') return null
  const start = Number(a.start_line)
  if (!Number.isFinite(start)) return null
  let end = start
  if (a.end_line !== undefined && a.end_line !== null) {
    const e = Number(a.end_line)
    if (!Number.isFinite(e)) return null
    end = e
  }
  return { path: a.path, ...normalizeRange(start, end) }
}

// --- rehype plugin: turn citations in *rendered text* into cdopen links ---
// Operating on the hast tree (not the markdown source) means fenced code,
// inline code and existing links are already distinct node types we can
// leave alone — preprocessing the source would corrupt code spans.

interface HastNode {
  type: string
  tagName?: string
  properties?: Record<string, unknown>
  children?: HastNode[]
  value?: string
}

/** Parents whose text must never become a link: code blocks/spans and links
 * themselves (an anchor inside an anchor is invalid HTML). */
const SKIP_PARENT = new Set(['code', 'pre', 'a'])

function linkifyNode(node: HastNode, parent?: HastNode): void {
  if (!node.children) return
  for (let i = 0; i < node.children.length; i++) {
    const child = node.children[i]
    if (child.type === 'text' && !(parent && parent.tagName && SKIP_PARENT.has(parent.tagName))) {
      const replacement = linkifyText(child)
      if (replacement) {
        node.children.splice(i, 1, ...replacement)
        i += replacement.length - 1
      }
    } else {
      linkifyNode(child, child)
    }
  }
}

function linkifyText(node: HastNode): HastNode[] | null {
  const text = node.value ?? ''
  CITATION_RE.lastIndex = 0
  const out: HastNode[] = []
  let last = 0
  let m: RegExpExecArray | null
  while ((m = CITATION_RE.exec(text)) !== null) {
    if (m.index > last) out.push({ type: 'text', value: text.slice(last, m.index) })
    out.push({
      type: 'element',
      tagName: 'a',
      properties: { href: citationHref(m), className: 'cd-cite' },
      children: [{ type: 'text', value: m[0] }],
    })
    last = m.index + m[0].length
  }
  if (!out.length) return null
  if (last < text.length) out.push({ type: 'text', value: text.slice(last) })
  return out
}

/** rehype plugin: `rehypePlugins={[rehypeCitations]}` on ReactMarkdown. */
export function rehypeCitations() {
  return (tree: HastNode) => {
    linkifyNode(tree)
    return tree
  }
}
