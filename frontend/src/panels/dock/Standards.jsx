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
import CodeEditor from '../../CodeEditor.jsx'
import { call } from '../../api'
import { errMsg } from '../../pollErrors'

// #234: a failed fetch must not look like an empty panel. Each of the three
// loads keeps its own failure line (one shared banner cannot say which mode
// is broken) and clears it on the next successful fetch.
function Failure({ children }) {
  return (
    <div
      data-poll-error="Standards"
      className="rounded border border-danger/40 bg-danger/10 p-2 text-xs text-danger"
    >{children}</div>
  )
}

// R59 P0: lifted out of DockPanel's `tab === 'Standards'` branch with its own
// state, unchanged. It never read the dock's shared `data`, so it becomes a
// self-contained panel — directives editor, skills manager, review checklist.
export function Standards({ sessionId }) {
  const [stdMode, setStdMode] = useState('directives')
  const [directivesDraft, setDirectivesDraft] = useState(null)
  const [skillList, setSkillList] = useState(null)
  const [reviewChecklist, setReviewChecklist] = useState(null)
  const [editingSkill, setEditingSkill] = useState(null)
  const [savedMsg, setSavedMsg] = useState('')
  const [errors, setErrors] = useState({})

  useEffect(() => {
    if (!sessionId) return
    call(`/sessions/${sessionId}/standards`)
      .then((d) => { setReviewChecklist(d.review_checklist); setErrors((e) => ({ ...e, checklist: null })) })
      .catch((err) => setErrors((e) => ({ ...e, checklist: errMsg(err) })))
    call('/skills/detail')
      .then((l) => { setSkillList(l); setErrors((e) => ({ ...e, skills: null })) })
      .catch((err) => setErrors((e) => ({ ...e, skills: errMsg(err) })))
    call('/directives')
      .then((d) => { setDirectivesDraft((cur) => cur ?? d.content); setErrors((e) => ({ ...e, directives: null })) })
      .catch((err) => { setDirectivesDraft(''); setErrors((e) => ({ ...e, directives: errMsg(err) })) })
  }, [sessionId])

  async function saveDirectives() {
    await call('/directives', { method: 'PUT', body: JSON.stringify({ content: directivesDraft }) })
    setSavedMsg('directives saved — enforced from the next run')
    setTimeout(() => setSavedMsg(''), 2500)
  }

  async function startEditSkill(name) {
    const list = await call('/skills/detail')
    setEditingSkill(list.find((s) => s.name === name) || null)
  }

  async function saveSkill() {
    if (!editingSkill?.name) return
    await call(`/skills/detail/${encodeURIComponent(editingSkill.name)}`, {
      method: 'PUT',
      body: JSON.stringify({ description: editingSkill.description, body: editingSkill.body }),
    })
    setEditingSkill(null)
    call('/skills/detail').then(setSkillList).catch(() => {})
  }

  async function deleteSkill(name) {
    // Auth is the HttpOnly session cookie — no bearer header exists (L13).
    await fetch(`/api/skills/detail/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }).then((r) => r.json())
    setSkillList((list) => list.filter((s) => s.name !== name))
  }

  const modes = ['directives', 'skills', 'checklist']
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex gap-1">
        {modes.map((m) => (
          <button
            key={m}
            className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${stdMode === m ? 'bg-neutral-800 text-brand-300' : 'text-neutral-500 hover:text-neutral-300'}`}
            onClick={() => setStdMode(m)}
          >{m}</button>
        ))}
      </div>
      {savedMsg && <div className="rounded bg-success/15 px-2 py-1 text-[10px] text-brand-300">{savedMsg}</div>}
      {errors.directives && <Failure>could not load directives: {errors.directives}</Failure>}
      {errors.skills && <Failure>could not load skills: {errors.skills}</Failure>}
      {errors.checklist && <Failure>could not load review checklist: {errors.checklist}</Failure>}

      {stdMode === 'directives' && (
        <div className="flex min-h-0 flex-1 flex-col gap-1">
          <div className="text-[10px] text-neutral-500">
            ~/.codingdude/DIRECTIVES.md — enforced on every run (project AGENT.md adds on top)
          </div>
          <div className="min-h-0 flex-1 overflow-hidden rounded border border-neutral-700">
            <CodeEditor
              path="DIRECTIVES.md"
              value={directivesDraft ?? ''}
              onChange={setDirectivesDraft}
              height="100%"
            />
          </div>
          <button
            className="self-start rounded bg-brand-700 px-3 py-1 text-xs text-brand-fg hover:bg-brand-600"
            onClick={saveDirectives}
          >Save directives</button>
        </div>
      )}

      {stdMode === 'skills' && !editingSkill && (
        <div className="flex flex-1 flex-col gap-1 overflow-y-auto">
          <button
            className="self-start rounded bg-brand-700 px-2 py-1 text-[10px] text-brand-fg"
            onClick={() => setEditingSkill({ name: 'new-skill', description: '', body: '' })}
          >+ new skill</button>
          {skillList && skillList.map((s) => (
            <div key={s.name} className="flex items-start justify-between gap-1 rounded bg-neutral-900 p-1">
              <div className="min-w-0">
                <div className="text-xs text-neutral-200">{s.name}</div>
                <div className="truncate text-[10px] text-neutral-500">{s.description}</div>
              </div>
              <div className="flex shrink-0 gap-1">
                <button className="text-[10px] text-accent" onClick={() => startEditSkill(s.name)}>edit</button>
                <button className="text-[10px] text-danger" onClick={() => deleteSkill(s.name)}>del</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {stdMode === 'skills' && editingSkill && (
        <div className="flex min-h-0 flex-1 flex-col gap-1">
          <input
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            value={editingSkill.name}
            onChange={(e) => setEditingSkill({ ...editingSkill, name: e.target.value })}
            placeholder="skill-name"
          />
          <input
            className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            value={editingSkill.description}
            onChange={(e) => setEditingSkill({ ...editingSkill, description: e.target.value })}
            placeholder="when should the agent use this skill?"
          />
          <div className="min-h-0 flex-1 overflow-hidden rounded border border-neutral-700">
            <CodeEditor
              path={`${editingSkill.name}.md`}
              value={editingSkill.body}
              onChange={(v) => setEditingSkill({ ...editingSkill, body: v })}
              height="100%"
            />
          </div>
          <div className="flex gap-1">
            <button className="rounded bg-brand-700 px-3 py-1 text-xs text-brand-fg" onClick={saveSkill}>save skill</button>
            <button className="rounded bg-neutral-700 px-3 py-1 text-xs text-ink" onClick={() => setEditingSkill(null)}>cancel</button>
          </div>
        </div>
      )}

      {stdMode === 'checklist' && (
        <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap rounded bg-neutral-900 p-2 text-[11px] text-neutral-400">
          {reviewChecklist ?? (errors.checklist ? '' : 'loading…')}
        </pre>
      )}
    </div>
  )
}
