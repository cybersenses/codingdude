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
// R59 P3: REQ-5 — every move has a non-drag path. The palette's command
// list and dispatch are exercised against a recorded fake api so the labels,
// guards and calls are pinned without a renderer.
import { describe, expect, it } from 'vitest'
import { commandList, filterCommands, runCommand, type CommandApi } from './commands'
import { PRESETS } from './catalogue'

function fakeApi(overrides: Partial<CommandApi> = {}): CommandApi & { calls: string[] } {
  const calls: string[] = []
  const panels = [
    { id: 'nav' },
    { id: 'editor' },
    { id: 'chat' },
  ]
  const groups = [{ id: 'g1', api: { location: { type: 'grid' } } }]
  const api = {
    calls,
    panels,
    activePanel: { id: 'editor' },
    groups,
    getPanel: (id: string) =>
      panels.some((p) => p.id === id)
        ? {
            id,
            api: {
              setActive: () => calls.push(`setActive:${id}`),
              moveTo: (opts: { group: { id: string }; position: string }) =>
                calls.push(`moveTo:${id}:${opts.group.id}:${opts.position}`),
            },
            group: groups[0],
          }
        : undefined,
    addPanel: (opts: Record<string, unknown>) => {
      calls.push(`addPanel:${opts.id}:${JSON.stringify(opts.position ?? null)}`)
      panels.push({ id: String(opts.id) })
      return opts
    },
    addFloatingGroup: (item: unknown) => calls.push(`float:${String((item as { id: string }).id)}`),
    addPopoutGroup: (item: unknown) => {
      calls.push(`popout:${String((item as { id: string }).id)}`)
      return Promise.resolve(true)
    },
    removePanel: (p: unknown) => {
      calls.push(`removePanel:${String((p as { id: string }).id)}`)
      const i = panels.findIndex((x) => x.id === (p as { id: string }).id)
      if (i >= 0) panels.splice(i, 1)
    },
    ...overrides,
  } as unknown as CommandApi & { calls: string[]; panels: Array<{ id: string }> }
  return api
}

const ctx = (extra: Record<string, string[]> = {}) => ({
  applyPreset: (id: string) => extra.applied?.push(id),
  savePresetAs: () => extra.saved?.push('y'),
  userPresets: extra.userPresets ?? [],
})

describe('commandList', () => {
  it('offers Show for closed panels and Hide for open ones', () => {
    const api = fakeApi()
    const cmds = commandList(api, ctx())
    const label = (id: string) => cmds.find((c) => c.id === id)?.label
    expect(label('hide:editor')).toBe('Hide Editor')
    expect(label('show:trace')).toBe('Show Trace')
    expect(cmds.find((c) => c.id === 'show:editor')).toBeUndefined()
    expect(cmds.find((c) => c.id === 'hide:trace')).toBeUndefined()
  })

  it('offers the four moves, Float and Pop out for the active panel only', () => {
    const cmds = commandList(fakeApi(), ctx())
    const moves = cmds.filter((c) => c.group === 'move').map((c) => c.id)
    expect(moves).toEqual(['move:editor:left', 'move:editor:right', 'move:editor:above', 'move:editor:below', 'float:editor', 'popout:editor'])
  })

  it('offers Dock (not Pop out) when the active panel is popped out', () => {
    const api = fakeApi()
    ;(api as unknown as { getPanel: unknown }).getPanel = (id: string) => ({
      id,
      api: { setActive: () => {}, moveTo: () => {} },
      group: { id: 'g9', api: { location: { type: 'popout' } } },
    })
    const cmds = commandList(api, ctx())
    expect(cmds.find((c) => c.id === 'dock:editor')?.label).toBe('Dock Editor')
    expect(cmds.find((c) => c.id === 'popout:editor')).toBeUndefined()
    expect(cmds.find((c) => c.id === 'float:editor')).toBeUndefined()
  })

  it('omits moves when no panel is active', () => {
    const api = fakeApi({ activePanel: undefined })
    expect(commandList(api, ctx()).filter((c) => c.group === 'move')).toEqual([])
  })

  it('offers Dock instead of Float when the active panel is floating', () => {
    const api = fakeApi()
    const gridGroup = { id: 'g1', api: { location: { type: 'grid' } } }
    ;(api as unknown as { getPanel: unknown }).getPanel = (id: string) => ({
      id,
      api: {
        setActive: () => {},
        moveTo: (o: { position: string }) => (api as unknown as { calls: string[] }).calls.push(`moveTo:${id}:${o.group.id}:${o.position}`),
      },
      group: { id: 'g9', api: { location: { type: 'floating' } } },
    })
    const cmds = commandList(api, ctx())
    expect(cmds.find((c) => c.group === 'move' && c.id.startsWith('float'))).toBeUndefined()
    expect(cmds.find((c) => c.id === 'dock:editor')?.label).toBe('Dock Editor')
  })

  it('lists user presets and save-as', () => {
    const cmds = commandList(fakeApi(), ctx({ userPresets: ['Debug'] }))
    expect(cmds.find((c) => c.id === 'preset:Debug')?.label).toBe('Apply preset: Debug')
    expect(cmds.find((c) => c.id === 'preset:save-as')).toBeDefined()
  })
})

describe('filterCommands', () => {
  it('filters case-insensitively on label and passes everything on empty query', () => {
    const cmds = commandList(fakeApi(), ctx())
    expect(filterCommands(cmds, 'trac').map((c) => c.id)).toEqual(['show:trace'])
    expect(filterCommands(cmds, 'hide ed').map((c) => c.id)).toEqual(['hide:editor'])
    expect(filterCommands(cmds, '').length).toBe(cmds.length)
  })
})

describe('runCommand', () => {
  it('shows a closed panel into the active group and focuses it', () => {
    const api = fakeApi()
    expect(runCommand('show:trace', api, ctx())).toBe(true)
    expect(api.calls).toEqual(['addPanel:trace:{"direction":"within","referencePanel":"editor"}', 'setActive:trace'])
  })

  it('shows into an empty layout without a reference', () => {
    const api = fakeApi({ panels: [], activePanel: undefined })
    expect(runCommand('show:trace', api, ctx())).toBe(true)
    expect(api.calls).toEqual(['addPanel:trace:null', 'setActive:trace'])
  })

  it('shows into the grid when the active panel is popped out', () => {
    // R59 P4: referencing the active panel while it lives in a popout window
    // would pull the new panel into that OS window — probed live. The command
    // must fall back to a grid-resident panel instead.
    const api = fakeApi()
    const panels = (api as unknown as { panels: Array<{ id: string }> }).panels
    const popGroup = { id: 'g9', api: { location: { type: 'popout' } } }
    ;(api as unknown as { getPanel: unknown }).getPanel = (id: string) => ({
      id,
      api: {
        setActive: () => (api as unknown as { calls: string[] }).calls.push(`setActive:${id}`),
        moveTo: () => {},
      },
      group: id === 'nav' ? { id: 'g1', api: { location: { type: 'grid' } } } : popGroup,
    })
    expect(runCommand('show:trace', api, ctx())).toBe(true)
    expect(api.calls[0]).toBe('addPanel:trace:{"direction":"within","referencePanel":"nav"}')
  })

  it('hides an open panel', () => {
    const api = fakeApi()
    expect(runCommand('hide:chat', api, ctx())).toBe(true)
    expect(api.calls).toEqual(['removePanel:chat'])
  })

  it('refuses to hide a closed panel or show an open one', () => {
    const api = fakeApi()
    expect(runCommand('hide:trace', api, ctx())).toBe(false)
    expect(runCommand('show:editor', api, ctx())).toBe(false)
  })

  it('moves the panel relative to its own group', () => {
    const api = fakeApi()
    expect(runCommand('move:editor:below', api, ctx())).toBe(true)
    expect(api.calls).toEqual(['moveTo:editor:g1:bottom', 'setActive:editor'])
  })

  it('floats the panel', () => {
    const api = fakeApi()
    expect(runCommand('float:chat', api, ctx())).toBe(true)
    expect(api.calls).toEqual(['float:chat', 'setActive:chat'])
  })

  it('pops the panel out to its own window', () => {
    const api = fakeApi()
    expect(runCommand('popout:chat', api, ctx())).toBe(true)
    expect(api.calls).toEqual(['popout:chat'])
    return new Promise<void>((resolve) =>
      setTimeout(() => {
        expect(api.calls).toEqual(['popout:chat', 'setActive:chat'])
        resolve()
      }, 0),
    )
  })

  it('refuses to pop out an unknown panel', () => {
    expect(runCommand('popout:nope', fakeApi(), ctx())).toBe(false)
  })

  it('delegates presets to the shell and returns false for unknown ids', () => {
    const applied: string[] = []
    const c = { applyPreset: (id: string) => applied.push(id), savePresetAs: () => {}, userPresets: [] }
    const api = fakeApi()
    expect(runCommand('preset:default', api, c)).toBe(true)
    expect(runCommand('layout:reset', api, c)).toBe(true)
    expect(applied).toEqual(['default', 'default'])
    expect(runCommand('nope', api, c)).toBe(false)
  })
})

describe('shipped preset ids round-trip through the palette', () => {
  it('accepts every shipped preset id', () => {
    const applied: string[] = []
    const c = { applyPreset: (id: string) => applied.push(id), savePresetAs: () => {}, userPresets: [] }
    const api = fakeApi()
    for (const p of PRESETS) expect(runCommand(`preset:${p.id}`, api, c)).toBe(true)
    expect(applied).toEqual(PRESETS.map((p) => p.id))
  })
})
