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
import { PANELS, PRESETS, panelSpec, panelOptions } from './catalogue'

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
  /** R59 P4: pop the panel out to its own OS window. Resolves false when the
   * window could not be opened (popup blocker etc.); the shell also receives
   * the failure via onDidOpenPopoutWindowFail. */
  addPopoutGroup(item: unknown, opts?: Record<string, unknown>): Promise<boolean>
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
      })
    }
    const location = api.getPanel(activeId)?.group.api.location.type
    const docked = location === 'floating' || location === 'popout'
    const activeTitle = panelSpec(activeId)?.title ?? activeId
    cmds.push({
      id: docked ? `dock:${activeId}` : `float:${activeId}`,
      label: docked ? `Dock ${activeTitle}` : `Float ${activeTitle}`,
      group: 'move',
    })
    // R59 P4: pop the panel out to its own window (keyboard/drag-free path).
    if (location !== 'popout') {
      cmds.push({
        id: `popout:${activeId}`,
        label: `Pop out ${activeTitle} to a window`,
        group: 'move',
      })
    }
  }

  for (const preset of PRESETS) {
    if (preset.id !== 'default') {
      cmds.push({ id: `preset:${preset.id}`, label: `Apply preset: ${preset.title}`, group: 'preset' })
    }
  }
  for (const name of ctx.userPresets) {
    cmds.push({ id: `preset:${name}`, label: `Apply preset: ${name}`, group: 'preset' })
  }
  cmds.push({ id: 'preset:save-as', label: 'Save layout as preset…', group: 'preset' })

  cmds.push({ id: 'layout:reset', label: 'Reset layout (default preset)', group: 'layout' })
  return cmds
}

/** Case-insensitive substring filter for the palette list. */
export function filterCommands(cmds: PaletteCommand[], query: string): PaletteCommand[] {
  const q = query.trim().toLowerCase()
  if (!q) return cmds
  return cmds.filter((c) => c.label.toLowerCase().includes(q))
}

/**
 * Where a `show:` panel is docked when it is added to the grid.
 * `reference` undefined = no position argument: an empty layout has nothing to
 * dock against, so dockview seeds the first group.
 */
export interface PanelPlacement {
  reference?: string
  direction: 'below' | 'within'
}

/**
 * First open panel living in the grid that is not nav — the shared deep-link
 * fallback reference. nav (the sidebar column) must never host a panel: a
 * 'within' placement there is a tab strip in a ~256px column (#331's band
 * shape, generalized to every panel family by #334).
 */
function firstNonNavGridPanel(
  openIds: string[],
  inGrid: (panelId?: string) => boolean,
): string | undefined {
  return openIds.find((p) => inGrid(p) && p !== 'nav')
}

/**
 * R87 #328 / R88 #331: the Artifacts deep-link placement policy.
 *
 * A deep-link open (chat-card View, nav, palette) must not merge into the
 * active group as a tab — that buried the editor behind an EditorArtifacts
 * strip and persisted the merged layout on the debounced save. With an editor
 * present it becomes its own group BELOW it (mirrors diff-below-editor).
 *
 * Without an editor the historic `anyGridPanel` fallback picked nav (first in
 * panel creation order), so Artifacts docked as a ~305px band inside the
 * sidebar column — probed live 2026-11-13 on the user's saved layout. The
 * fallback therefore joins the chat group as a tab (its historic home), and
 * only falls to another grid panel when chat is gone. 'below' stays reserved
 * for the editor: splitting a fallback group's height would recreate exactly
 * the cramped band this prevents.
 */
export function artifactsPlacement(
  openIds: string[],
  inGrid: (panelId?: string) => boolean,
): PanelPlacement {
  if (openIds.includes('editor') && inGrid('editor')) {
    return { reference: 'editor', direction: 'below' }
  }
  if (openIds.includes('chat') && inGrid('chat')) {
    return { reference: 'chat', direction: 'within' }
  }
  return { reference: firstNonNavGridPanel(openIds, inGrid), direction: 'within' }
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
    const inGrid = (panelId: string | undefined) =>
      panelId !== undefined && api.getPanel(panelId)?.group.api.location.type === 'grid'
    // Reference the active panel *unless it lives outside the grid* — a
    // floating or popped-out active panel would otherwise pull the new panel
    // into its floating overlay / OS window, which reads as "Show did
    // nothing" in the main window (probed in .scratch/p4_popout_probe.py).
    const activeId = api.activePanel?.id
    // R87 #328 / R88 #331: Artifacts has its own placement policy - the why
    // lives on `artifactsPlacement()`. Every other panel keeps the historic
    // dock-within-active placement, with one #334 carve-out: nav is never a
    // reference — not as the active panel, not as the fallback scan — or the
    // panel lands as a sidebar-column tab (the #331 band shape) and the
    // debounced save persists it.
    const placement: PanelPlacement =
      pid === 'artifacts'
        ? artifactsPlacement(openIds, inGrid)
        : {
            reference:
              activeId !== undefined && activeId !== 'nav' && inGrid(activeId)
                ? activeId
                : firstNonNavGridPanel(openIds, inGrid),
            direction: 'within',
          }
    api.addPanel({
      ...panelOptions(spec),
      // An empty layout has no reference: dockview seeds the first group.
      ...(placement.reference !== undefined
        ? { position: { direction: placement.direction, referencePanel: placement.reference } }
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
    // Re-docking a floating or popped-out panel: moving it 'center' into the
    // first grid group merges it back as a tab (dockview closes the popout
    // window / floating overlay it came from). The group here is the live
    // DockviewGroupPanel from api.groups, narrowed to this module's view.
    const gridGroup = api.groups.find((g) => g.api.location.type === 'grid')
    if (!gridGroup) return false
    panel.api.moveTo({ group: gridGroup as unknown as { id: string }, position: 'center' })
    return true
  }
  if (id.startsWith('popout:')) {
    const panel = api.getPanel(id.slice(7))
    if (!panel) return false
    // Failure is surfaced by the shell's onDidOpenPopoutWindowFail notice; the
    // promise is fire-and-forget so the palette stays synchronous.
    void api.addPopoutGroup(panel).then(() => panel.api.setActive())
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
