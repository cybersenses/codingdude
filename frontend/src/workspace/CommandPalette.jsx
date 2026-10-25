// CodingDude — a personal coding agent.
// Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the Affero General Public License as published
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
// R59 P3 (tech design #1 §4.6): the command palette. dockview's own keyboard
// docking is an enterprise feature, so without this the workspace would be
// mouse-only (REQ-5). The list itself comes from commands.ts, which reads the
// catalogue — this component is only chrome: open/close, filter, focus, run.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { commandList, filterCommands, runCommand } from './commands'

const GROUP_TITLES = { panel: 'Panels', move: 'Move', preset: 'Presets', layout: 'Layout' }

export function CommandPalette({ api, ctx }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const [tick, setTick] = useState(0) // layout changed → rebuild the command list
  const inputRef = useRef(null)

  // Global binding: Ctrl+Shift+P and the Ctrl+K alias. Keydown on window so
  // the palette opens from anywhere in the shell, including inside Monaco
  // (Monaco's own Ctrl+K chords are not blocked — the bare Ctrl+K with no
  // follow-up key opens the palette).
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'p') {
        e.preventDefault()
        setOpen(true)
        setQuery('')
        setIndex(0)
      } else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen(true)
        setQuery('')
        setIndex(0)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  const commands = useMemo(
    () => (api && open ? commandList(api, ctx) : []),
    // Rebuilt on open and after every executed command (tick): the list must
    // reflect the mutated layout, not the one it opened against.
    [api, open, tick, ctx.userPresets.length],
  )
  const visible = useMemo(() => filterCommands(commands, query), [commands, query])
  const safeIndex = Math.min(index, Math.max(0, visible.length - 1))

  function exec(i) {
    const cmd = visible[i]
    if (!cmd || cmd.disabled || !api) return
    runCommand(cmd.id, api, ctx)
    setOpen(false)
    setQuery('')
    // The next open rebuilds from the mutated layout anyway; bump now so a
    // rapid reopen cannot show the pre-mutation list.
    setTick((t) => t + 1)
  }

  if (!open || !api) return null
  return (
    <div
      data-palette
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 pt-24"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false)
      }}
    >
      <div className="w-[32rem] overflow-hidden rounded border border-line bg-neutral-900 shadow-2xl">
        <input
          ref={inputRef}
          data-palette-input
          className="w-full border-b border-line bg-transparent px-3 py-2 text-sm text-ink outline-none"
          placeholder="type a command… (panels, move, presets)"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setIndex(0)
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setIndex((i) => Math.min(i + 1, visible.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setIndex((i) => Math.max(i - 1, 0))
            } else if (e.key === 'Enter') {
              e.preventDefault()
              exec(safeIndex)
            } else if (e.key === 'Escape') {
              setOpen(false)
            }
          }}
        />
        <div className="max-h-80 overflow-y-auto py-1">
          {visible.length === 0 && (
            <div className="px-3 py-2 text-xs text-ink-muted">no matching command</div>
          )}
          {visible.map((cmd, i) => (
            <button
              key={cmd.id}
              data-palette-item={cmd.id}
              className={`block w-full px-3 py-1.5 text-left text-xs ${
                i === safeIndex ? 'bg-brand-700/60 text-ink' : 'text-neutral-300 hover:bg-surface'
              } ${cmd.disabled ? 'opacity-40' : ''}`}
              onMouseEnter={() => setIndex(i)}
              onClick={() => exec(i)}
            >
              <span className="mr-2 text-[10px] uppercase tracking-wide text-ink-muted">
                {GROUP_TITLES[cmd.group]}
              </span>
              {cmd.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
