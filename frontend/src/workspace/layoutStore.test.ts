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
// R59 P3: REQ-8 — a layout that fails to restore must never brick the UI,
// and REQ-2 — a good one must survive reload. Every branch of the load
// decision is exercised here against an in-memory storage.
import { describe, expect, it, vi } from 'vitest'
import {
  LAYOUT_KEY,
  LAYOUT_VERSION,
  PRESETS_KEY,
  clearSavedLayout,
  createDebouncedSaver,
  deleteUserPreset,
  loadSavedLayout,
  loadUserPresets,
  panelIds,
  presetNameValid,
  saveLayout,
  saveUserPreset,
  stripUnknownPanels,
  type KVStorage,
  type SerializedLayout,
} from './layoutStore'
import { isKnownPanel, PRESETS } from './catalogue'

function memStorage(initial: Record<string, string> = {}): KVStorage {
  const map = new Map(Object.entries(initial))
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
  }
}

/** A minimal but structurally faithful serialized dockview layout. */
function sampleLayout(): SerializedLayout {
  return {
    grid: {
      root: {
        type: 'branch',
        data: [
          { type: 'leaf', data: { id: 'g1', views: ['nav'], activeView: 'nav' }, size: 1 },
          { type: 'leaf', data: { id: 'g2', views: ['editor', 'diff'], activeView: 'diff' }, size: 3 },
        ],
      },
      height: 800,
      width: 1200,
      orientation: 'HORIZONTAL',
    },
    panels: {
      nav: { id: 'nav', component: 'nav' },
      editor: { id: 'editor', component: 'editor' },
      diff: { id: 'diff', component: 'diff' },
    },
    activeGroup: 'g2',
    floatingGroups: [{ data: { id: 'g3', views: ['terminal'] }, position: { x: 1, y: 2, width: 10, height: 10 } }],
    popoutGroups: [],
  }
}

describe('loadSavedLayout', () => {
  it('round-trips a saved layout', () => {
    const storage = memStorage()
    saveLayout(storage, sampleLayout(), 'custom')
    const res = loadSavedLayout(storage, isKnownPanel)
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.preset).toBe('custom')
      expect(panelIds(res.layout).sort()).toEqual(['diff', 'editor', 'nav', 'terminal'])
    }
  })

  it('reports missing when nothing was saved', () => {
    expect(loadSavedLayout(memStorage(), isKnownPanel)).toEqual({ ok: false, reason: 'missing' })
  })

  it('falls back on corrupt JSON', () => {
    const storage = memStorage({ [LAYOUT_KEY]: '{not json' })
    expect(loadSavedLayout(storage, isKnownPanel)).toEqual({ ok: false, reason: 'corrupt' })
  })

  it('falls back on a non-object layout', () => {
    const storage = memStorage({ [LAYOUT_KEY]: JSON.stringify({ v: LAYOUT_VERSION, preset: 'x', layout: 42 }) })
    expect(loadSavedLayout(storage, isKnownPanel)).toEqual({ ok: false, reason: 'corrupt' })
  })

  it('falls back on a future version', () => {
    const storage = memStorage({ [LAYOUT_KEY]: JSON.stringify({ v: LAYOUT_VERSION + 1, preset: 'x', layout: sampleLayout() }) })
    expect(loadSavedLayout(storage, isKnownPanel)).toEqual({ ok: false, reason: 'version' })
  })

  it('falls back when storage throws (quota/privacy)', () => {
    const storage: KVStorage = {
      getItem: () => {
        throw new Error('quota')
      },
      setItem: () => {
        throw new Error('quota')
      },
    }
    expect(loadSavedLayout(storage, isKnownPanel)).toEqual({ ok: false, reason: 'corrupt' })
    expect(saveLayout(storage, sampleLayout(), 'x')).toBe(false)
  })

  it('falls back when the grid shape is malformed', () => {
    const bad = sampleLayout()
    ;(bad.grid as Record<string, unknown>).root = { type: 'leaf', data: 'not-a-group' }
    const storage = memStorage()
    saveLayout(storage, bad, 'custom')
    expect(loadSavedLayout(storage, isKnownPanel)).toEqual({ ok: false, reason: 'corrupt' })
  })

  it('drops unknown panels and keeps the rest', () => {
    const layout = sampleLayout()
    layout.panels!['oldpanel'] = { id: 'oldpanel', component: 'oldpanel' }
    const g2 = (layout.grid!.root as { data: Array<{ data: { views: string[] } }> }).data[1]
    g2.data.views = ['editor', 'oldpanel', 'diff']
    const storage = memStorage()
    saveLayout(storage, layout, 'custom')
    const res = loadSavedLayout(storage, isKnownPanel)
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.dropped).toEqual(['oldpanel'])
      expect(panelIds(res.layout).sort()).toEqual(['diff', 'editor', 'nav', 'terminal'])
      expect(Object.keys(res.layout.panels!)).not.toContain('oldpanel')
    }
  })

  it('drops unknown panels inside floating windows', () => {
    const layout = sampleLayout()
    layout.floatingGroups = [{ data: { id: 'g3', views: ['gone', 'terminal'], activeView: 'gone' }, position: {} }]
    const dropped = stripUnknownPanels(layout, isKnownPanel)
    expect(dropped).toEqual(['gone'])
    const win = layout.floatingGroups![0] as { data: { views: string[] } }
    expect(win.data.views).toEqual(['terminal'])
    expect((win.data as Record<string, unknown>).activeView).toBeUndefined()
  })

  it('falls back when stripping leaves no panels at all', () => {
    const layout = sampleLayout()
    layout.floatingGroups = []
    layout.popoutGroups = []
    const nav = (layout.grid!.root as { data: Array<{ data: { views: string[] } }> }).data[0]
    nav.data.views = ['retired']
    const g2 = (layout.grid!.root as { data: Array<{ data: { views: string[] } }> }).data[1]
    g2.data.views = []
    const storage = memStorage()
    saveLayout(storage, layout, 'custom')
    expect(loadSavedLayout(storage, isKnownPanel)).toEqual({ ok: false, reason: 'empty' })
  })

  it('clear loads as missing (silent default), never corrupt', () => {
    const storage = memStorage()
    saveLayout(storage, sampleLayout(), 'x')
    clearSavedLayout(storage)
    // clearSavedLayout stores '' (the KVStorage seam has no removeItem); it
    // must read as "nothing saved", not as corruption. Workspace writes this
    // after a corrupt/version fallback so the reset notice shows once.
    expect(loadSavedLayout(storage, isKnownPanel)).toEqual({ ok: false, reason: 'missing' })
  })
})

describe('user presets', () => {
  it('saves, lists and deletes a preset', () => {
    const storage = memStorage()
    expect(saveUserPreset(storage, 'Debug', sampleLayout())).toBe(true)
    expect(Object.keys(loadUserPresets(storage))).toEqual(['Debug'])
    deleteUserPreset(storage, 'Debug')
    expect(loadUserPresets(storage)).toEqual({})
  })

  it('rejects hostile preset names', () => {
    const storage = memStorage()
    for (const bad of ['', ' ', '../etc', 'x'.repeat(40), 'a\nb']) {
      expect(saveUserPreset(storage, bad, sampleLayout())).toBe(false)
    }
    expect(storage.getItem(PRESETS_KEY)).toBeNull()
  })

  it('validates names without touching storage', () => {
    expect(presetNameValid('Debug 2')).toBe(true)
    expect(presetNameValid('my-preset_x')).toBe(true)
    expect(presetNameValid('')).toBe(false)
    expect(presetNameValid('a/b')).toBe(false)
  })

  it('rejects names that collide with shipped preset ids or the reserved verb', () => {
    // A user preset named like a shipped id would emit a duplicate
    // `preset:<name>` command id and be unreachable (`presetById` wins).
    // Derived, not hardcoded: a future shipped preset must be covered here
    // the day it lands, not the day someone remembers this list.
    for (const reserved of [...PRESETS.map((p) => p.id), 'save-as']) {
      expect(presetNameValid(reserved)).toBe(false)
      expect(saveUserPreset(memStorage(), reserved, sampleLayout())).toBe(false)
    }
  })

  it('returns {} on corrupt preset storage', () => {
    const storage = memStorage({ [PRESETS_KEY]: 'zzz' })
    expect(loadUserPresets(storage)).toEqual({})
  })

  it('a preset named __proto__ round-trips instead of vanishing', () => {
    // NAME_RE legitimately matches "__proto__"; on a plain object the
    // assignment would hit Object.prototype's setter and save an empty
    // record while reporting success (post-push review finding).
    const storage = memStorage()
    expect(saveUserPreset(storage, '__proto__', sampleLayout())).toBe(true)
    expect(Object.keys(loadUserPresets(storage))).toEqual(['__proto__'])
    deleteUserPreset(storage, '__proto__')
    expect(Object.keys(loadUserPresets(storage))).toEqual([])
  })
})

describe('createDebouncedSaver', () => {
  it('coalesces a burst into one write', () => {
    vi.useFakeTimers()
    const save = vi.fn()
    const saver = createDebouncedSaver(save, 400)
    saver.schedule()
    saver.schedule()
    saver.schedule()
    expect(save).not.toHaveBeenCalled()
    vi.advanceTimersByTime(400)
    expect(save).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('cancel prevents the write', () => {
    vi.useFakeTimers()
    const save = vi.fn()
    const saver = createDebouncedSaver(save, 400)
    saver.schedule()
    saver.cancel()
    vi.advanceTimersByTime(1000)
    expect(save).not.toHaveBeenCalled()
    expect(saver.pending()).toBe(false)
    vi.useRealTimers()
  })
})
