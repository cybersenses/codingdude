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
import logoUrl from '../assets/logo.png'

// R59 P0: moved verbatim out of App.jsx. Projects + sessions navigator; becomes
// the `nav` panel in P1, so its state stays local to the component.
export function Sidebar({ workdir, setWorkdir, sessions, activeSession, onSelect, onNewSession, width, runningSessions, projects, activeProject, onSelectProject, onAddProject, onDeleteProject }) {
  const [newProjectName, setNewProjectName] = useState(null)
  return (
    <aside className="flex shrink-0 flex-col gap-3 border-r border-neutral-800 bg-neutral-950 p-3" style={{ width }}>
      <div className="flex items-center gap-2">
        <img src={logoUrl} alt="CodingDude logo" className="h-6 w-6 rounded" />
        <h1 className="text-lg font-bold text-brand-400">CodingDude</h1>
      </div>
      <label className="text-xs text-neutral-400">
        Project
        <select
          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-200"
          value={activeProject?.id ?? ''}
          onChange={(e) => {
            const p = projects.find((x) => x.id === Number(e.target.value))
            if (p) onSelectProject(p)
          }}
        >
          <option value="">— select project —</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </label>
      {activeProject && (
        <div className="flex items-center justify-between text-[10px] text-neutral-500">
          <span className="truncate font-mono">{activeProject.workdir}</span>
          <button
            className="text-danger hover:opacity-80"
            title="remove project from list (files are not touched)"
            aria-label="Remove project from list"
            onClick={() => onDeleteProject(activeProject.id)}
          >✕</button>
        </div>
      )}
      <label className="text-xs text-neutral-400">
        Workdir
        <input
          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-200"
          value={workdir}
          onChange={(e) => setWorkdir(e.target.value)}
          placeholder="C:\path\to\project"
        />
      </label>
      {newProjectName !== null ? (
        <div className="flex flex-col gap-1 rounded border border-neutral-700 bg-neutral-900 p-2">
          <input
            className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            placeholder="project name"
            autoFocus
          />
          <div className="truncate text-[10px] text-neutral-500">folder: {workdir || '— set workdir above —'}</div>
          <div className="flex gap-1">
            <button
              className="rounded bg-success px-2 py-1 text-[10px] text-success-fg disabled:opacity-40"
              disabled={!newProjectName.trim() || !workdir.trim()}
              onClick={() => {
                onAddProject(newProjectName.trim(), workdir.trim())
                setNewProjectName(null)
              }}
            >save project</button>
            <button
              className="rounded bg-neutral-700 px-2 py-1 text-[10px] text-ink"
              onClick={() => setNewProjectName(null)}
            >cancel</button>
          </div>
        </div>
      ) : (
        <button
          className="self-start rounded border border-neutral-700 px-2 py-1 text-[10px] text-neutral-400 hover:text-neutral-200"
          onClick={() => setNewProjectName('')}
        >+ New project</button>
      )}
      <button
        className="rounded bg-brand-700 px-2 py-1 text-sm font-medium text-brand-fg hover:bg-brand-600"
        onClick={onNewSession}
      >
        + New session
      </button>
      <div className="flex-1 overflow-y-auto">
        {sessions.map((s) => (
          <button
            key={s.session_id}
            className={`block w-full truncate rounded px-2 py-1 text-left text-sm ${
              s.session_id === activeSession
                ? 'bg-neutral-800 text-brand-300'
                : 'text-neutral-400 hover:bg-neutral-900'
            }`}
            onClick={() => onSelect(s.session_id)}
            title={s.title || s.session_id}
          >
            {s.title || s.session_id.slice(0, 12)}
            {runningSessions.has(s.session_id) && (
              <span className="ml-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-success" />
            )}
            {s.context_limit != null && s.context_tokens != null && s.context_tokens > 0 && (
              <span className="mt-0.5 flex items-center gap-1" title={`Context: ${Math.round((s.context_tokens / s.context_limit) * 100)}% of ${Math.round(s.context_limit / 1000)}k tokens`}>
                <span className="h-0.5 flex-1 overflow-hidden rounded bg-neutral-800">
                  <span
                    className={`block h-full ${
                      s.context_tokens / s.context_limit > 0.8 ? 'bg-danger' : 'bg-brand-600'
                    }`}
                    style={{ width: `${Math.min(100, (s.context_tokens / s.context_limit) * 100)}%` }}
                  />
                </span>
                <span className="text-[9px] text-neutral-500">
                  {Math.round((s.context_tokens / s.context_limit) * 100)}%
                </span>
              </span>
            )}
          </button>
        ))}
      </div>
    </aside>
  )
}
