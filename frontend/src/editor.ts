// Editor tab state + Monaco language mapping (pure logic, vitest-covered).

export interface FileTab {
  path: string
  content: string
  /** st_mtime_ns from the server at read time; sent back on save. */
  mtime: number | null
  active: boolean
}

export const MAX_TABS = 8

const LANGS: Record<string, string> = {
  py: 'python',
  js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
  ts: 'typescript', tsx: 'typescript', mts: 'typescript',
  md: 'markdown', markdown: 'markdown',
  css: 'css', scss: 'scss', less: 'less',
  html: 'html', htm: 'html',
  json: 'json',
  rs: 'rust', go: 'go', cs: 'csharp', c: 'c', h: 'c',
  cpp: 'cpp', cc: 'cpp', hpp: 'cpp',
  java: 'java', php: 'php', rb: 'ruby', swift: 'swift', kt: 'kotlin',
  yml: 'yaml', yaml: 'yaml', toml: 'ini', ini: 'ini',
  sh: 'shell', bash: 'shell', sql: 'sql', xml: 'xml', svg: 'xml',
  dart: 'dart', lua: 'lua', ex: 'elixir', exs: 'elixir',
  scala: 'scala', r: 'r', jl: 'julia', pl: 'perl', ps1: 'powershell',
}

/** Map a file path to its Monaco language id. */
export function langFor(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  return LANGS[ext] ?? 'plaintext'
}

/** Open (or re-activate) a file as a tab; evicts the oldest beyond MAX_TABS. */
export function openTab(
  tabs: FileTab[],
  file: { path: string; content: string; mtime: number | null },
): FileTab[] {
  const rest = tabs.filter((t) => t.path !== file.path)
  const evicted = rest.length >= MAX_TABS ? rest.slice(0, rest.length - MAX_TABS + 1) : []
  const kept = rest.slice(evicted.length)
  return [{ path: file.path, content: file.content, mtime: file.mtime, active: true },
    ...kept.map((t) => ({ ...t, active: false }))]
}

/** Close a tab; if it was active, activate its right neighbor (then last). */
export function closeTab(tabs: FileTab[], path: string): FileTab[] {
  const idx = tabs.findIndex((t) => t.path === path)
  if (idx === -1) return tabs
  const wasActive = tabs[idx].active
  const next = tabs.filter((t) => t.path !== path)
  if (wasActive && next.length > 0) {
    const neighbor = Math.min(idx, next.length - 1)
    next[neighbor] = { ...next[neighbor], active: true }
  }
  return next
}
