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
import React from 'react'
import { describeProcess } from '../processes'
import { shortStamp, UI_BUILD, UI_SHA, UI_VERSION } from '../ui.jsx'

// R59 P0: extracted from App's return value, markup unchanged. Stays chrome in
// the dockable workspace — it reports the shells' build, not a panel's.
export function StatusFooter({ activeSession, sessions, workdir, srv, theme, onToggleTheme, processes }) {
  return (
    <footer className="flex items-center justify-between border-t border-neutral-800 bg-neutral-950 px-3 py-1 text-[10px] text-neutral-500">
      <span>
        {activeSession ? `session ${activeSession.slice(0, 8)}` : 'no session'} ·{' '}
        {sessions.find((s) => s.session_id === activeSession)?.workdir || workdir || 'no workdir'}
        {activeSession && !sessions.some((s) => s.session_id === activeSession) && (
          <span className="text-danger"> · ⚠ session not in selected project</span>
        )}
      </span>
      <span className="text-neutral-600" title="frontend build · backend server build">
        ui v{UI_VERSION}{UI_SHA ? `+${UI_SHA}` : ''} {shortStamp(UI_BUILD)} · srv v{srv?.version ?? '?'}{srv?.git_sha ? `+${srv.git_sha}` : ''} {shortStamp(srv?.started_at)}
      </span>
      <button
        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-400 hover:text-neutral-200"
        title="toggle light / dark"
        onClick={onToggleTheme}
      >
        {theme === 'dark' ? 'dark' : 'light'}
      </button>
      {processes.length > 0 && (
        <span
          className="ml-2 cursor-help text-neutral-500"
          title={processes.map(describeProcess).join('\n')}
        >
          ⚙ {processes.filter((p) => p.status === 'running').length} live / {processes.length} spawned
        </span>
      )}
    </footer>
  )
}
