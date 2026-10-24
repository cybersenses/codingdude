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
import React, { useEffect, useState } from 'react'
import { call } from '../api'

// R59 P0: moved verbatim out of App.jsx. Becomes the `explorer` panel in P1.

export function TreeNode({ node, depth, onOpen }) {
  const [open, setOpen] = useState(depth < 1)
  if (node.type === 'dir') {
    return (
      <div>
        <button
          className="block w-full truncate text-left text-xs text-accent hover:opacity-80"
          style={{ paddingLeft: depth * 10 + 4 }}
          onClick={() => setOpen(!open)}
        >
          {open ? '▾' : '▸'} {node.name}
        </button>
        {open && node.children.map((c) => (
          <TreeNode key={c.path} node={c} depth={depth + 1} onOpen={onOpen} />
        ))}
      </div>
    )
  }
  return (
    <button
      className="block w-full truncate rounded px-1 text-left text-xs text-ink-muted hover:bg-surface hover:text-ink"
      style={{ paddingLeft: depth * 10 + 14 }}
      onClick={() => onOpen(node.path)}
      title={node.path}
    >
      {node.name}
    </button>
  )
}

// Left rail: full-height file tree for the active session.
export function FileTree({ sessionId, onOpen }) {
  const [tree, setTree] = useState(null)
  useEffect(() => {
    if (!sessionId) return
    let stop = false
    async function poll() {
      try {
        const t = await call(`/sessions/${sessionId}/tree`)
        if (!stop) setTree(t)
      } catch { /* transient */ }
      if (!stop) setTimeout(poll, 10000)
    }
    poll()
    return () => { stop = true }
  }, [sessionId])
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-1">
      {sessionId && tree ? tree.children.map((c) => (
        <TreeNode key={c.path} node={c} depth={0} onOpen={onOpen} />
      )) : <div className="text-neutral-600">{sessionId ? 'loading…' : 'no session'}</div>}
    </div>
  )
}
