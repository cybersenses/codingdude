import { describe, expect, it } from 'vitest'
import { closeTab, langFor, openTab } from './editor'

describe('langFor', () => {
  it('maps common suffixes to Monaco language ids', () => {
    expect(langFor('a.py')).toBe('python')
    expect(langFor('b.ts')).toBe('typescript')
    expect(langFor('c.tsx')).toBe('typescript')
    expect(langFor('d.jsx')).toBe('javascript')
    expect(langFor('e.md')).toBe('markdown')
    expect(langFor('f.css')).toBe('css')
    expect(langFor('g.html')).toBe('html')
    expect(langFor('h.json')).toBe('json')
    expect(langFor('i.rs')).toBe('rust')
    expect(langFor('j.go')).toBe('go')
    expect(langFor('k.cs')).toBe('csharp')
    expect(langFor('l.cpp')).toBe('cpp')
    expect(langFor('m.yml')).toBe('yaml')
    expect(langFor('n.toml')).toBe('ini')
    expect(langFor('o.sh')).toBe('shell')
  })
  it('falls back to plaintext', () => {
    expect(langFor('nope.unknown')).toBe('plaintext')
  })
})

describe('openTab', () => {
  const tab = (path: string) => ({ path, content: 'x', mtime: 1 })

  it('activates an existing tab without duplicating it', () => {
    const tabs = [tab('a.py'), tab('b.py')]
    const next = openTab(tabs, { path: 'a.py', content: 'new', mtime: 2 })
    expect(next.map((t) => t.path)).toEqual(['a.py', 'b.py'])
    expect(next[0].active).toBe(true)
    expect(next[0].content).toBe('new')
    expect(next[1].active).toBe(false)
  })

  it('prepends a new tab and makes it active', () => {
    const next = openTab([tab('a.py')], { path: 'b.py', content: 'y', mtime: 3 })
    expect(next.map((t) => t.path)).toEqual(['b.py', 'a.py'])
    expect(next[0].active).toBe(true)
  })

  it('caps the number of tabs, evicting the least recently opened', () => {
    let tabs = openTab([], { path: '1.py', content: '', mtime: 1 })
    for (let i = 2; i <= 9; i++) tabs = openTab(tabs, { path: `${i}.py`, content: '', mtime: 1 })
    const next = openTab(tabs, { path: '10.py', content: '', mtime: 1 })
    expect(next.length).toBe(8)
    expect(next.map((t) => t.path)).not.toContain('9.py')
    expect(next[0].path).toBe('10.py')
  })
})

describe('closeTab', () => {
  const mk = () => [
    { path: 'a.py', content: '', mtime: 1, active: false },
    { path: 'b.py', content: '', mtime: 1, active: true },
    { path: 'c.py', content: '', mtime: 1, active: false },
  ]

  it('activates the neighbor when closing the active tab', () => {
    const next = closeTab(mk(), 'b.py')
    expect(next.map((t) => t.path)).toEqual(['a.py', 'c.py'])
    expect(next[1].active).toBe(true)
  })

  it('keeps the active tab untouched when closing a background tab', () => {
    const next = closeTab(mk(), 'a.py')
    expect(next.map((t) => t.path)).toEqual(['b.py', 'c.py'])
    expect(next[0].active).toBe(true)
  })
})
