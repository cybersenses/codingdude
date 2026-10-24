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
import React, { useState } from 'react'
import CodeEditor, { CodeDiff } from '../CodeEditor.jsx'
import { closeTab } from '../editor'
import { call } from '../api'
import { ACTIONS, buildActionPrompt } from '../aiActions'

// R59 P0: moved verbatim out of App.jsx. Main area: tab strip + Monaco editor /
// diff for the shared workspace; becomes the `editor` panel in P1.
export function EditorPane({ ws, onAsk }) {
  const { sessionId, tabs, setTabs, draft, setDraft, dirty, setDirty, notice, setNotice, diff, setDiff, active, openFile } = ws
  const [selection, setSelection] = useState('')

  function activate(path) {
    const t = tabs.find((x) => x.path === path)
    if (!t) return
    setTabs(tabs.map((x) => ({ ...x, active: x.path === path })))
    setDraft(t.content)
    setDirty(false)
    setNotice(null)
    setDiff(null)
  }

  function close(path) {
    const next = closeTab(tabs, path)
    setTabs(next)
    const nowActive = next.find((t) => t.active)
    setDraft(nowActive ? nowActive.content : '')
    setDirty(false)
    setNotice(null)
    setDiff(null)
  }

  async function save() {
    if (!active) return
    try {
      const r = await call(`/sessions/${sessionId}/file`, {
        method: 'PUT',
        body: JSON.stringify({
          path: active.path, content: draft, expected_mtime: active.mtime,
        }),
      })
      setTabs(tabs.map((t) => (t.path === active.path
        ? { ...t, content: draft, mtime: r.mtime }
        : t)))
      setDirty(false)
      setNotice('saved ✓')
    } catch (e) {
      setNotice(e.message.includes('409')
        ? `${active.path} changed on disk since you opened it — reload to pick up the agent's version, then re-apply your edit.`
        : `save failed: ${e.message}`)
    }
    setTimeout(() => setNotice(null), 4000)
  }

  async function toggleDiff() {
    if (diff) { setDiff(null); return }
    if (!active) return
    try {
      const r = await call(`/sessions/${sessionId}/file_diff?path=${encodeURIComponent(active.path)}`)
      setDiff({ base: r.base })
    } catch (e) {
      setNotice(`diff failed: ${e.message}`)
      setTimeout(() => setNotice(null), 4000)
    }
  }

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-neutral-500">
        Open a file from the explorer or pick a session to chat.
      </div>
    )
  }
  if (tabs.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-neutral-500">
        Open a file from the explorer to start editing.
      </div>
    )
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1 p-2">
      <div className="flex items-center gap-0.5 overflow-x-auto">
        {tabs.map((t) => (
          <div key={t.path} className={`group flex items-center rounded-t border-b-2 px-2 py-0.5 text-[10px] ${t.active ? 'border-brand bg-neutral-800 text-ink' : 'border-transparent bg-neutral-900 text-ink-muted'}`}>
            <button className="max-w-40 truncate font-mono" onClick={() => activate(t.path)} title={t.path}>
              {t.path.split('/').pop()}
            </button>
            <button className="ml-1 text-neutral-500 hover:text-danger" onClick={() => close(t.path)}>×</button>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between">
        <span className="truncate font-mono text-[10px] text-brand-300">{active?.path}</span>
        <div className="flex gap-1">
          <button
            className="rounded bg-brand-700 px-2 py-0.5 text-[10px] text-brand-fg disabled:opacity-40"
            disabled={!dirty}
            onClick={save}
          >save</button>
          <button
            className="rounded bg-neutral-700 px-2 py-0.5 text-[10px] text-ink"
            onClick={() => active && openFile(active.path)}
          >reload</button>
          <button
            className={`rounded px-2 py-0.5 text-[10px] text-ink ${diff ? 'bg-brand-700 text-brand-fg' : 'bg-neutral-700'}`}
            disabled={!active}
            onClick={toggleDiff}
          >diff vs HEAD</button>
        </div>
      </div>
      {notice && <div className="text-[10px] text-brand-400">{notice}</div>}
      <div className="min-h-0 flex-1 overflow-hidden rounded border border-neutral-700">
        {diff
          ? (
            <CodeDiff
              path={active?.path || ''}
              original={diff.base}
              modified={draft}
              height="100%"
            />
          )
          : (
            <CodeEditor
              path={active?.path || ''}
              value={draft}
              onChange={(v) => { setDraft(v); setDirty(true) }}
              onSelectionChange={setSelection}
              height="100%"
            />
          )}
      </div>
      {selection.trim() && onAsk && (
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-neutral-500">
            {selection.split('\n').length} line{selection.split('\n').length === 1 ? '' : 's'} selected
          </span>
          {ACTIONS.map((a) => (
            <button
              key={a.id}
              className="rounded bg-neutral-700 px-2 py-0.5 text-[10px] text-ink hover:bg-brand-700 hover:text-brand-fg"
              onClick={() => {
                const prompt = buildActionPrompt(a.id, active?.path || '', selection)
                if (!prompt) return
                setSelection('')
                onAsk(prompt)
              }}
            >{a.label}</button>
          ))}
          <button
            className="rounded px-1 text-[10px] text-neutral-500 hover:text-danger"
            onClick={() => setSelection('')}
          >×</button>
        </div>
      )}
    </div>
  )
}
