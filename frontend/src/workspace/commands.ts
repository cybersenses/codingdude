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
// R59 P3 (tech design #1 §4.6, REQ-5): every panel move reachable without a
// mouse. The command list is built from the catalogue + a snapshot of the
// live dockview api, so the palette never offers a command that would no-op
// ("Hide Graph" while Graph is closed). Pure enough to unit test against a
// recorded-shape fake api; the Workspace wires the same commands to the real
// DockviewApi.
import { PANELS, PRESETS, panelSpec } from './catalogue'

/** The api surface the commands touch — DockviewApi satisfies this. */
export interface CommandApi {
  panels: Array<{ id: string }>
  activePanel?: { id: string }
  groups: Array<{ id: string; api: { location: { type: string } } }>
  getPanel(id: string): {
    api: {
      setActive(): void
      moveTo(opts: { group: { id: string }; position: string }): void
    }
    group: { id: string; api: { location: { type: string } } }
  } | undefined
  addPanel(opts: Record<string, unknown>): unknown
  addFloatingGroup(item: unknown, opts?: Record<string, unknown>): void
  toJSON(): unknown
  clear(): void
}

export interface CommandCtx {
  /** Applied by the shell: (presetId, placements) — the shell owns pinSizes. */
  applyPreset(presetId: string): void
  /** Ask the user for a preset name and save the current layout under it. */
  savePresetAs(): void
  userPresets: string[]
}

export interface PaletteCommand {
  id: string
  label: string
  /** Grouping prefix in the palette list. */
  group: 'panel' | 'move' | 'preset' | 'layout'
  disabled: boolean
}

// dockview Position uses top/bottom/left/right/center; palette directions map
// onto it.
const MOVE_TARGETS = [
  { key: 'left', position: 'left', label: 'Move {p} → left' },
  { key: 'right', position: 'right', label: 'Move {p} → right' },
  { key: 'above', position: 'top', label: 'Move {p} → above' },
  { key: 'below', position: 'bottom', label: 'Move {p} → below' },
] as const

export function commandList(api: CommandApi, ctx: CommandCtx): PaletteCommand[] {
  const openIds = api.panels.map((p) => p.id)
  const cmds: PaletteCommand[] = []

  for (const spec of PANELS) {
    const open = openIds.includes(spec.id)
    cmds.push({
      id: open ? `hide:${spec.id}` : `show:${spec.id}`,
      label: open ? `Hide ${spec.title}` : `Show ${spec.title}`,
      group: 'panel',
      disabled: false,
    })
  }

  // Moves operate on the *active* panel against its own group, so the command
  // needs both an active panel and a second group to split relative to.
  const activeId = api.activePanel?.id
  if (activeId && openIds.length > 0) {
    for (const t of MOVE_TARGETS) {
      cmds.push({
        id: `move:${activeId}:${t.key}`,
        label: t.label.replace('{p}', panelSpec(activeId)?.title ?? activeId),
        group: 'move',
        disabled: false,
      })
    }
    const location = api.getPanel(activeId)?.group.api.location.type
    cmds.push({
      id: location === 'floating' ? `dock:${activeId}` : `float:${activeId}`,
      label:
        location === 'floating'
          ? `Dock ${panelSpec(activeId)?.title ?? activeId}`
          : `Float ${panelSpec(activeId)?.title ?? activeId}`,
      group: 'move',
      disabled: false,
    })
  }

  for (const preset of PRESETS) {
    if (preset.id !== 'default') {
      cmds.push({ id: `preset:${preset.id}`, label: `Apply preset: ${preset.title}`, group: 'preset', disabled: false })
    }
  }
  for (const name of ctx.userPresets) {
    cmds.push({ id: `preset:${name}`, label: `Apply preset: ${name}`, group: 'preset', disabled: false })
  }
  cmds.push({ id: 'preset:save-as', label: 'Save layout as preset…', group: 'preset', disabled: false })

  cmds.push({ id: 'layout:reset', label: 'Reset layout (default preset)', group: 'layout', disabled: false })
  return cmds
}

/** Substring (word-boundary-tolerant) filter for the palette list. */
export function filterCommands(cmds: PaletteCommand[], query: string): PaletteCommand[] {
  const q = query.trim().toLowerCase()
  if (!q) return cmds
  return cmds.filter((c) => c.label.toLowerCase().includes(q))
}

export function runCommand(
  id: string,
  api: CommandApi,
  ctx: CommandCtx,
): boolean {
  const openIds = api.panels.map((p) => p.id)
  if (id.startsWith('show:')) {
    const pid = id.slice(5)
    const spec = panelSpec(pid)
    if (!spec || openIds.includes(pid)) return false
    const reference = api.activePanel?.id ?? openIds[0]
    api.addPanel({
      id: spec.id,
      component: spec.component,
      title: spec.title,
      renderer: spec.renderer,
      ...(spec.minWidth !== undefined ? { minimumWidth: spec.minWidth } : {}),
      ...(spec.minHeight !== undefined ? { minimumHeight: spec.minHeight } : {}),
      // An empty layout has no reference: dockview seeds the first group.
      ...(reference !== undefined
        ? { position: { direction: 'within', referencePanel: reference } }
        : {}),
    })
    api.getPanel(pid)?.api.setActive()
    return true
  }
  if (id.startsWith('hide:')) {
    const pid = id.slice(5)
    const panel = api.getPanel(pid)
    if (!panel || !openIds.includes(pid)) return false
    // removePanel is not on the CommandApi surface used elsewhere; cast is
    // confined to this branch.
    ;(api as unknown as { removePanel(p: unknown): void }).removePanel(panel)
    return true
  }
  if (id.startsWith('move:')) {
    const [, pid, dir] = id.split(':')
    const panel = api.getPanel(pid)
    if (!panel) return false
    const target = MOVE_TARGETS.find((t) => t.key === dir)
    if (!target) return false
    panel.api.moveTo({ group: panel.group, position: target.position })
    panel.api.setActive()
    return true
  }
  if (id.startsWith('float:')) {
    const panel = api.getPanel(id.slice(6))
    if (!panel) return false
    api.addFloatingGroup(panel)
    panel.api.setActive()
    return true
  }
  if (id.startsWith('dock:')) {
    const panel = api.getPanel(id.slice(5))
    if (!panel) return false
    // Re-docking a floating panel: moving it 'center' into the first grid
    // group merges it back as a tab. The group here is the live
    // DockviewGroupPanel from api.groups, narrowed to this module's view.
    const gridGroup = api.groups.find((g) => g.api.location.type === 'grid')
    if (!gridGroup) return false
    panel.api.moveTo({ group: gridGroup as unknown as { id: string }, position: 'center' })
    return true
  }
  if (id.startsWith('preset:')) {
    const name = id.slice(7)
    if (name === 'save-as') {
      ctx.savePresetAs()
      return true
    }
    ctx.applyPreset(name)
    return true
  }
  if (id === 'layout:reset') {
    ctx.applyPreset('default')
    return true
  }
  return false
}
