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

// R59 P0: moved verbatim out of App.jsx. Health strip above the editor — the
// one surface that stays chrome (not a panel) in the dockable workspace.
export function AgentStrip({ status, quietSeconds, hasChanges, streaming, onReviewChanges }) {
  const stalled = streaming && quietSeconds >= 120
  return (
    <div className="flex h-7 shrink-0 items-center gap-3 border-b border-neutral-800 bg-neutral-950 px-3 text-[11px]">
      <span className={streaming ? 'text-brand-400' : 'text-neutral-500'}>
        <span
          className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${streaming ? 'animate-pulse bg-brand-400' : 'bg-neutral-600'}`}
        />
        agent {status || 'idle'}
      </span>
      {streaming && quietSeconds > 0 && (
        <span className={stalled ? 'text-red-400' : 'text-neutral-500'}>quiet {quietSeconds}s</span>
      )}
      {hasChanges && (
        <button
          className="ml-auto rounded bg-brand-700 px-2 py-0.5 text-[10px] font-medium text-white hover:bg-brand-600"
          onClick={onReviewChanges}
        >
          Review changes →
        </button>
      )}
    </div>
  )
}
