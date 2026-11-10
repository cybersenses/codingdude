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
import React, { useEffect, useRef, useState } from 'react'
import { call } from '../api'
import { checklistPrompt } from '../checklists'
import { registerComposerPrefill } from '../composerPrefill'

// R59 P0: moved verbatim out of App.jsx. The prompt row sits directly above the
// chat panel and is docked with it in P1.
import { modelOptions, pickerSelection, resolveModelSend, CUSTOM_OPTION } from '../modelpick'

// R83: the composer's model picker. A native <select> (never filters its
// options — the datalist combobox this replaces offered only entries matching
// the already-typed text, locking a persisted pick to itself) plus a
// free-typed custom input. The send contract stays resolveModelSend.
export function ModelPicker({ models, model, setModel }) {
  const selection = pickerSelection(models, model)
  const [customOpen, setCustomOpen] = useState(selection === CUSTOM_OPTION)
  const showSuffix = () => {
    const send = resolveModelSend(models, model)
    return !send.literal && send.send
      ? <span className="text-[10px] text-neutral-500">→ {send.send}</span>
      : null
  }
  if (customOpen) {
    return (
      <span className="flex items-center gap-1">
        <select
          className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
          value={CUSTOM_OPTION}
          aria-label="Model"
          title="Per-run model: a configured slot, or a custom provider:model typed below."
          onChange={(e) => {
            setCustomOpen(false)
            setModel(e.target.value)
          }}
        >
          <option value="">default (main)</option>
          {modelOptions(models).map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
          <option value={CUSTOM_OPTION}>custom…</option>
        </select>
        <input
          className="w-36 min-w-0 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
          value={model}
          placeholder="provider:model"
          aria-label="Custom model"
          autoFocus
          onChange={(e) => setModel(e.target.value)}
        />
        {showSuffix()}
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1">
      <select
        className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-ink"
        value={selection}
        aria-label="Model"
        title="Per-run model: a configured slot, or custom… to type provider:model. Default = the configured main model."
        onChange={(e) => {
          if (e.target.value === CUSTOM_OPTION) { setCustomOpen(true); return }
          setModel(e.target.value)
        }}
      >
        <option value="">default (main)</option>
        {modelOptions(models).map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
        <option value={CUSTOM_OPTION}>custom…</option>
      </select>
      {showSuffix()}
    </span>
  )
}

export function Prompt({ onSend, disabled, running = false, suggestMode, setSuggestMode, fixLoop, setFixLoop, models, modelsError, model, setModel, yolo, setYolo, longRun, setLongRun, notify, toggleNotify }) {
  const [text, setText] = useState('')
  // R85 #317 (REQ-7): the composer prefill seam's composer half — panels
  // (wireframe implement buttons) call prefillComposer; this registration is
  // the only writer of the seam's setter slot, cleared on unmount.
  useEffect(() => {
    registerComposerPrefill(setText)
    return () => registerComposerPrefill(null)
  }, [])
  const [image, setImage] = useState(null) // {b64, name}
  const [checklists, setChecklists] = useState(null) // null = picker not opened yet
  const fileRef = useRef(null)
  // notify state is owned by App (single source of truth, L13) and passed in.
  // #230: `disabled` has two causes — no session, or a run in flight. They are
  // not interchangeable: "select a session" while the agent is working is a
  // lie that invites the user to navigate away from a live run.
  const placeholder = !disabled
    ? 'describe the task… (Enter to send, Shift+Enter for newline)'
    : running
      ? 'the agent is working — press Stop to interrupt…'
      : 'create or select a session first'

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
          // R67 #254: resize-y so a long prompt can be grown to read in full
          // (the user request behind R65) - bounded so the composer cannot
          // eat the chat. rows={2} is the initial height.
          className="min-h-[3.25rem] max-h-64 min-w-0 flex-1 resize-y rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
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
          placeholder={placeholder}
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
      {/* #307: models-unavailable keeps its honest error state. R83: the
          datalist combobox is gone — Chromium filtered its suggestions against
          the input's own value, so a persisted pick (localStorage cd-model)
          locked the dropdown to that one entry. A real <select> always shows
          every slot plus a visible "default (main)" reset; "custom…" reveals
          the free-text provider:model input. resolveModelSend still owns what
          is sent; the suffix shows the resolved name so an alias choice is
          never mistaken for the literal string. */}
      {modelsError ? (
        <select
          className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-warning"
          value=""
          disabled
          title={modelsError}
          aria-label="Model"
        >
          <option value="">models unavailable</option>
        </select>
      ) : (
        <ModelPicker models={models} model={model} setModel={setModel} />
      )}
      <label className={`flex items-center gap-1 text-[10px] ${yolo ? 'text-danger' : 'text-neutral-400'}`} title="yolo = the approval-policy switch: auto-approve every gated action for this session. It is NOT the long-run mode — see --long-run.">
        <input type="checkbox" checked={yolo} onChange={(e) => setYolo(e.target.checked)} />
        yolo
      </label>
      <select
        className={`rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs ${longRun ? 'text-warning' : 'text-ink'}`}
        value={longRun}
        disabled={disabled}
        title="Long-run work mode for this run (per-run, resets to off): sandbox lane, durable resume, evidence gate, evaluator, publish cycle. assisted = still stops with one publish card at the end; unattended = publishes its branch + draft PR on its own. Composes with — but is NOT — the yolo approval switch. Merge/ready stays yours either way."
        aria-label="Long-run level"
        onChange={(e) => setLongRun(e.target.value)}
      >
        <option value="">long run: off</option>
        <option value="assisted">long run: assisted</option>
        <option value="unattended">long run: unattended</option>
      </select>
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
