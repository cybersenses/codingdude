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
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.
// #256 (R68): the Planning panel must reflect agent-created planning items.
// The panel joins the visibility-gated store with a `planning` topic whose
// store key is the WORKDIR (planning is project-scoped, not session-scoped),
// so the fetcher maps that key straight to api.getPlanning. These tests pin
// the fetcher seam; the poll-while-visible semantics it inherits live in
// sessionData.test.ts.
import { beforeEach, describe, expect, it, vi } from 'vitest'

// The fetchers close over the real api module; mock it so the tests assert
// the mapping without touching the network or a server.
vi.mock('../api', () => ({
  api: { getPlanning: vi.fn() },
  call: vi.fn(),
}))

import { api } from '../api'
import { requiresSession, sessionTopics } from './sessionTopics'

const getPlanning = vi.mocked(api.getPlanning)
const empty = { roadmap: [], tickets: [], decisions: [], prds: [], designs: [] }

beforeEach(() => {
  getPlanning.mockReset()
  getPlanning.mockResolvedValue(empty)
})

describe('planning topic', () => {
  it('maps the store key (the workdir) to api.getPlanning', async () => {
    await expect(sessionTopics.planning?.('G:\\proj')).resolves.toEqual(empty)
    expect(getPlanning).toHaveBeenCalledWith('G:\\proj')
  })

  it('resolves null without fetching when no workdir is selected', async () => {
    // The panel subscribes with workdir || null; the guard keeps the null
    // key from hammering /api/planning/ forever (the requiresSession guard
    // cannot, because planning must poll on a session-less workspace).
    await expect(sessionTopics.planning?.(null)).resolves.toBeNull()
    await expect(sessionTopics.planning?.('')).resolves.toBeNull()
    expect(getPlanning).not.toHaveBeenCalled()
  })

  it('is not session-required: it must poll on a fresh workspace with no session', () => {
    expect(requiresSession('planning')).toBe(false)
  })
})
