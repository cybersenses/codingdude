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
// R85 #317 (REQ-7): implement handoff — composer prefill seam + per-screen
// button. Module tests here; button render smoke in wireframes.test.ts.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { implementPrompt, prefillComposer, registerComposerPrefill } from './composerPrefill'

afterEach(() => registerComposerPrefill(null))

describe('implementPrompt', () => {
  it('renders the REQ-7 handoff directive exactly', () => {
    expect(implementPrompt('Library', 'Admin pack', 'wf_1')).toBe(
      'Implement the "Library" screen from wireframe pack "Admin pack" (wf_1); treat that artifact as the spec.',
    )
  })
})

describe('prefillComposer', () => {
  it('delivers to the registered composer', () => {
    const fn = vi.fn()
    registerComposerPrefill(fn)
    expect(prefillComposer('hello')).toBe(true)
    expect(fn).toHaveBeenCalledWith('hello')
  })

  it('is honest when no composer is mounted', () => {
    expect(prefillComposer('hello')).toBe(false)
  })

  it('unregistering clears the seam', () => {
    const fn = vi.fn()
    registerComposerPrefill(fn)
    registerComposerPrefill(null)
    expect(prefillComposer('hello')).toBe(false)
    expect(fn).not.toHaveBeenCalled()
  })
})
