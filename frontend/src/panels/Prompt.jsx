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
import React, { useRef, useState } from 'react'
import { call } from '../api'
import { checklistPrompt } from '../checklists'

// R59 P0: moved verbatim out of App.jsx. The prompt row sits directly above the
// chat panel and is docked with it in P1.
export function Prompt({ onSend, disabled, suggestMode, setSuggestMode, fixLoop, setFixLoop, models, model, setModel, yolo, setYolo, notify, toggleNotify }) {
  const [text, setText] = useState('')
  const [image, setImage] = useState(null) // {b64, name}
  const [checklists, setChecklists] = useState(null) // null = picker not opened yet
  const fileRef = useRef(null)
  // notify state is owned by App (single source of truth, L13) and passed in.

  // #93: checklist picker — load the list on first open, send a checklist run on pick.
  async function pickChecklist(name) {
    if (!name || disabled) return
    const md = await call(`/checklists/${name}`)
    onSend(checklistPrompt(name, md.markdown, ''))
  }

  return (
    <form
      className="flex flex-col gap-2 border-b border-neutral-800 p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (text.trim() || image) {
          onSend(text.trim() || 'describe this image', image)
          setText('')
          setImage(null)
        }
      }}
    >
      <div className="flex items-end gap-2">
        <textarea
          className="min-w-0 flex-1 resize-none rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              if (text.trim() || image) {
                onSend(text.trim() || 'describe this image', image)
                setText('')
                setImage(null)
              }
            }
          }}
          placeholder={disabled ? 'create or select a session first' : 'describe the task… (Enter to send, Shift+Enter for newline)'}
          disabled={disabled}
        />
        <button
          className="rounded bg-brand-700 px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand-600 disabled:opacity-40"
          disabled={disabled}
        >
          Send
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
      {image && (
        <div className="flex items-center gap-1 rounded bg-neutral-900 px-2 py-1 text-[10px] text-success">
          {image.name}
          <button type="button" aria-label="Remove image" className="text-danger" onClick={() => setImage(null)}>✕</button>
        </div>
      )}
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files && e.target.files[0]
          if (!f) return
          const reader = new FileReader()
          reader.onload = () => setImage({ b64: String(reader.result).split(',')[1], name: f.name })
          reader.readAsDataURL(f)
          e.target.value = ''
        }}
      />
      <button
        type="button"
        className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-400 hover:text-neutral-200 disabled:opacity-40"
        onClick={() => fileRef.current && fileRef.current.click()}
        disabled={disabled}
        title="attach image"
        aria-label="Attach image"
      >
        📎
      </button>
      <label className="flex items-center gap-1 text-[10px] text-neutral-400" title="agent edits become proposals you can revert">
        <input type="checkbox" checked={suggestMode} onChange={(e) => setSuggestMode(e.target.checked)} />
        suggest
      </label>
      <select
        className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
        value=""
        disabled={disabled}
        title="run a distilled review checklist against the project"
        aria-label="Checklist"
        onChange={async (e) => {
          const name = e.target.value
          e.target.value = ''
          if (!checklists) {
            const r = await call('/checklists')
            setChecklists(r.checklists)
          }
          pickChecklist(name)
        }}
        onFocus={async () => {
          if (!checklists) {
            const r = await call('/checklists')
            setChecklists(r.checklists)
          }
        }}
      >
        <option value="">checklist…</option>
        {(checklists || []).map((c) => (
          <option key={c.name} value={c.name}>{c.title || c.name}</option>
        ))}
      </select>
      <label className="flex items-center gap-1 text-[10px] text-neutral-400" title="run tests after the task and fix failures until green (max 3 rounds)">
        <input type="checkbox" checked={fixLoop} onChange={(e) => setFixLoop(e.target.checked)} />
        fix until green
      </label>
      {models && (
        <select
          className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          title={model && models.models[model] ? models.models[model] : 'configured default (main)'}
          aria-label="Model"
        >
          <option value="">default (main)</option>
          {['main', 'subagent', 'fallback', 'vision'].map((k) =>
            models.models[k] ? <option key={k} value={k}>{k} — {models.models[k]}</option> : null
          )}
        </select>
      )}
      <label className={`flex items-center gap-1 text-[10px] ${yolo ? 'text-danger' : 'text-neutral-400'}`} title="auto-approve every gated action for this session">
        <input type="checkbox" checked={yolo} onChange={(e) => setYolo(e.target.checked)} />
        yolo
      </label>
      <label
        className={`cursor-pointer text-sm ${notify ? '' : 'grayscale opacity-50'}`}
        title="notify when a run finishes or waits"
        aria-label="Toggle notifications"
        onClick={toggleNotify}
      >
        🔔
      </label>
      </div>
    </form>
  )
}
