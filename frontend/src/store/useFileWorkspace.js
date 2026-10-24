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
import { useState } from 'react'
import { call } from '../api'
import { openTab } from '../editor'

// R35 #72: tree and editor share tab state, so the workspace state lives in
// one hook (used once, in App); the tree renders in the left rail and the
// editor in the main area.
// R59 P0: moved verbatim out of App.jsx into store/ — the shell owns it, the
// explorer and editor panels receive it.
export function useFileWorkspace(sessionId) {
  const [tabs, setTabs] = useState([]) // FileTab[] from editor.ts
  const [draft, setDraft] = useState('')
  const [dirty, setDirty] = useState(false)
  const [notice, setNotice] = useState(null)
  const [diff, setDiff] = useState(null) // {base} when diff view is on
  const active = tabs.find((t) => t.active) || null

  async function openFile(path) {
    try {
      const f = await call(`/sessions/${sessionId}/file?path=${encodeURIComponent(path)}`)
      setTabs(openTab(tabs, { path, content: f.content, mtime: f.mtime }))
      setDraft(f.content)
      setDirty(false)
      setNotice(null)
      setDiff(null)
    } catch (e) {
      setNotice(`cannot open ${path}: ${e.message}`)
    }
  }
  return { sessionId, tabs, setTabs, draft, setDraft, dirty, setDirty, notice, setNotice, diff, setDiff, active, openFile }
}
