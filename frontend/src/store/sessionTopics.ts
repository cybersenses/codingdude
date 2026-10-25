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
// R59 P2: the topic fetchers for the visibility-gated store. Each entry
// mirrors the corresponding branch of the classic DockPanel's per-tab poll
// (App.jsx), so a panel renders the same payload shape it always did — the
// store changes WHO fetches and WHEN, not WHAT comes back.
//
// Session-independent topics (config, memory) ignore the sessionId argument:
// the store keys them under null so they poll on a fresh workspace too.
import { api, call } from '../api'
import type { TopicFetcher } from './sessionData'

// Topics whose fetcher embeds the session id in the URL (or otherwise needs a
// selected session). `config` and `memory` are deliberately absent: they are
// session-independent and must keep polling on a fresh workspace.
const SESSION_REQUIRED = new Set([
  'diff', 'cost', 'mcp', 'renders', 'trace', 'output', 'processes',
])

export function requiresSession(topic: string): boolean {
  return SESSION_REQUIRED.has(topic)
}

export const sessionTopics: Record<string, TopicFetcher> = {
  diff: async (sid) => {
    const r = await call(`/sessions/${sid}/diff`)
    return { diff: r.diff, diffSummary: r.summary || [], impact: r.impact || null }
  },
  cost: (sid) => call(`/sessions/${sid}/usage`),
  memory: async () => call('/memory'),
  config: async () => call('/config/models'),
  mcp: (sid) => api.listMcp(sid),
  renders: async (sid) => {
    const r = await call(`/sessions/${sid}/renders`)
    return { renders: r.renders, renderStart: r.session_start }
  },
  trace: async (sid) => ({
    trace: await call(`/sessions/${sid}/trace?limit=50`),
    checkpoints: await call(`/sessions/${sid}/checkpoints`),
  }),
  output: async (sid) => ({
    runs: await call(`/sessions/${sid}/runs`),
    runEvents: await call(`/sessions/${sid}/trace?limit=300`),
  }),
  processes: (sid) => call(`/sessions/${sid}/processes`).then((rows) => rows || []),
}
