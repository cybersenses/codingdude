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
// R59 P1: the dock shell's invariants. These are the failures that would
// otherwise surface as a blank screen at runtime — dockview throws when a
// placement names a panel that does not exist yet, and silently renders
// nothing when a catalogue entry has no registered component.
import { describe, expect, it } from 'vitest'
import { DEFAULT_PRESET, GEOMETRY, PANELS, PRESETS, isKnownPanel, panelOptions, panelSpec, presetById } from './catalogue'

// The component registry lives in Workspace.jsx; keep this list in step with it.
const REGISTERED = [
  'nav', 'explorer', 'editor', 'chat', 'diff',
  // R59 P2
  'graph', 'planning', 'artifacts', 'notes', 'renders', 'terminal', 'output',
  'waterfall', 'trace', 'cost', 'memory', 'mcp', 'config', 'standards', 'processes',
]

describe('panel catalogue', () => {
  it('panelOptions maps a spec to addPanel options', () => {
    // The extraction exists so minimums reach dockview's resize clamp —
    // pin the mapping itself, not just the callers' payloads.
    const editor = panelOptions(panelSpec('editor')!)
    expect(editor).toEqual({
      id: 'editor',
      component: 'editor',
      title: 'Editor',
      renderer: 'always',
    })
    const nav = panelOptions(panelSpec('nav')!)
    expect(nav).toEqual({
      id: 'nav',
      component: 'nav',
      title: 'Projects & sessions',
      minimumWidth: GEOMETRY.sidebar.min,
    })
  })

  it('has unique panel ids', () => {
    const ids = PANELS.map((p) => p.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('has unique component names', () => {
    const names = PANELS.map((p) => p.component)
    expect(new Set(names).size).toBe(names.length)
  })

  it('only ships panels that have a registered component', () => {
    for (const p of PANELS) expect(REGISTERED).toContain(p.component)
  })

  it('registers a component for every shipped panel (no orphan renderers)', () => {
    for (const name of REGISTERED) {
      expect(PANELS.some((p) => p.component === name)).toBe(true)
    }
  })

  it('keeps stateful panels alive while hidden', () => {
    // REQ-4: a move re-parents the DOM node; the chat transcript and the
    // Monaco buffer must not be torn down and rebuilt on every drag.
    expect(panelSpec('chat')?.renderer).toBe('always')
    expect(panelSpec('editor')?.renderer).toBe('always')
  })

  it('resolves known ids and rejects unknown ones', () => {
    expect(isKnownPanel('chat')).toBe(true)
    expect(isKnownPanel('processes')).toBe(true) // P2
    expect(panelSpec('nope')).toBeUndefined()
  })
})

describe('default preset', () => {
  // The preset places the five first-boot panels (REQ-7); the P2 catalogue
  // entries are opened on demand from the command palette, not on boot.
  const PRESET_IDS = ['nav', 'explorer', 'editor', 'chat', 'diff']

  it('places exactly the five boot panels, once each', () => {
    expect(DEFAULT_PRESET.map((p) => p.id).sort()).toEqual([...PRESET_IDS].sort())
  })

  it('seeds the grid with a reference-free first placement', () => {
    expect(DEFAULT_PRESET[0].referencePanel).toBeUndefined()
    expect(DEFAULT_PRESET[0].direction).toBeUndefined()
  })

  it('only references panels placed before it', () => {
    // dockview resolves a reference panel eagerly: a forward reference throws
    // at mount time. This is the invariant that keeps the preset orderable.
    const seen: string[] = []
    for (const p of DEFAULT_PRESET) {
      expect(isKnownPanel(p.id)).toBe(true)
      if (p.referencePanel !== undefined) {
        expect(seen).toContain(p.referencePanel)
      }
      seen.push(p.id)
    }
  })

  it('gives every non-seed placement a direction', () => {
    for (const p of DEFAULT_PRESET.slice(1)) expect(p.direction).toBeDefined()
  })

  it('reproduces the classic column widths on first boot (REQ-7)', () => {
    const width = (id: string) => DEFAULT_PRESET.find((p) => p.id === id)?.initialWidth
    expect(width('nav')).toBe(GEOMETRY.sidebar.fallback)
    expect(width('explorer')).toBe(GEOMETRY.rail.fallback)
    expect(width('chat')).toBe(GEOMETRY.right.fallback)
  })

  it('realises the documented arrangement: diff under the editor, chat on the right', () => {
    const byId = new Map(DEFAULT_PRESET.map((p) => [p.id, p]))
    expect(byId.get('explorer')).toMatchObject({ direction: 'right', referencePanel: 'nav' })
    expect(byId.get('editor')).toMatchObject({ direction: 'right', referencePanel: 'explorer' })
    expect(byId.get('chat')).toMatchObject({ direction: 'right', referencePanel: 'editor' })
    expect(byId.get('diff')).toMatchObject({ direction: 'below', referencePanel: 'editor' })
  })

  it('never asks for a size smaller than the panel minimum it inherits', () => {
    for (const p of DEFAULT_PRESET) {
      const spec = panelSpec(p.id)
      if (p.initialWidth !== undefined && spec?.minWidth !== undefined) {
        expect(p.initialWidth).toBeGreaterThanOrEqual(spec.minWidth)
      }
      if (p.initialHeight !== undefined && spec?.minHeight !== undefined) {
        expect(p.initialHeight).toBeGreaterThanOrEqual(spec.minHeight)
      }
    }
  })
})

// R59 P3: the shipped presets are placements, so every invariant the default
// preset test asserts applies to each of them too — a forward reference or a
// duplicate id in ANY preset would throw at mount time when the user applies
// it from the palette.
describe('shipped presets', () => {
  const presetIds = ['default', 'debug', 'review', 'watching']

  it('exposes the four documented presets with unique ids', () => {
    expect(PRESETS.map((p) => p.id)).toEqual(presetIds)
    expect(new Set(PRESETS.map((p) => p.id)).size).toBe(PRESETS.length)
  })

  it('resolves every preset id', () => {
    for (const id of presetIds) expect(presetById(id)).toBeDefined()
    expect(presetById('nope')).toBeUndefined()
  })

  it('only references panels placed before it, in every preset', () => {
    for (const preset of PRESETS) {
      const seen: string[] = []
      for (const p of preset.placements) {
        expect(isKnownPanel(p.id)).toBe(true)
        if (p.referencePanel !== undefined) {
          expect(seen).toContain(p.referencePanel)
        }
        seen.push(p.id)
      }
      expect(new Set(seen).size).toBe(seen.length) // no duplicates
    }
  })

  it('seeds each preset grid with exactly one reference-free placement', () => {
    for (const preset of PRESETS) {
      expect(preset.placements[0].referencePanel).toBeUndefined()
      expect(preset.placements[0].direction).toBeUndefined()
      for (const p of preset.placements.slice(1)) expect(p.direction).toBeDefined()
    }
  })

  it('never asks for a size below the panel minimum, in any preset', () => {
    for (const preset of PRESETS) {
      for (const p of preset.placements) {
        const spec = panelSpec(p.id)
        if (p.initialWidth !== undefined && spec?.minWidth !== undefined) {
          expect(p.initialWidth).toBeGreaterThanOrEqual(spec.minWidth)
        }
        if (p.initialHeight !== undefined && spec?.minHeight !== undefined) {
          expect(p.initialHeight).toBeGreaterThanOrEqual(spec.minHeight)
        }
      }
    }
  })

  it('realises the documented review three-up and watching arrangement', () => {
    const review = presetById('review')!.placements
    const byId = new Map(review.map((p) => [p.id, p]))
    expect(byId.get('diff')).toMatchObject({ direction: 'below', referencePanel: 'editor' })
    expect(byId.get('waterfall')).toMatchObject({ direction: 'right', referencePanel: 'diff' })
    expect(byId.get('output')).toMatchObject({ direction: 'right', referencePanel: 'waterfall' })
    const watching = presetById('watching')!.placements
    const wById = new Map(watching.map((p) => [p.id, p]))
    expect(wById.get('processes')).toMatchObject({ direction: 'below', referencePanel: 'diff' })
  })
})
