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
import { describe, expect, it } from 'vitest'
import { pollCleared, pollFailure, tabError } from './pollErrors'

describe('pollFailure (#233)', () => {
  it('stamps the failure with the session it belongs to', () => {
    const out = pollFailure(undefined, 'Cost', 's1', new Error('boom'))
    expect(out.Cost).toEqual({ sessionId: 's1', message: 'boom' })
  })

  it('stamps null when there is no session', () => {
    const out = pollFailure(undefined, 'Config', undefined, new Error('boom'))
    expect(out.Config.sessionId).toBeNull()
  })

  it('keeps every other tab\u2019s error intact', () => {
    const before = pollFailure(undefined, 'Cost', 's1', new Error('first'))
    const after = pollFailure(before, 'MCP', 's1', new Error('second'))
    expect(after.Cost.message).toBe('first')
    expect(after.MCP.message).toBe('second')
  })

  it('carries a non-Error rejection value through as text', () => {
    // The poll catches whatever the fetch threw, which is not always an Error.
    expect(pollFailure(undefined, 'Cost', 's1', 'plain string').Cost.message).toBe('plain string')
  })
})

describe('pollCleared (#233)', () => {
  it('removes only the named tab', () => {
    const both = { Cost: { sessionId: 's1', message: 'a' }, MCP: { sessionId: 's1', message: 'b' } }
    const out = pollCleared(both, 'Cost')
    expect(out).toEqual({ MCP: { sessionId: 's1', message: 'b' } })
  })

  it('returns the same reference when there is nothing to clear', () => {
    // A healthy tab must not hand `data` a fresh object every 4 seconds.
    const errors = { MCP: { sessionId: 's1', message: 'b' } }
    expect(pollCleared(errors, 'Cost')).toBe(errors)
    expect(pollCleared(undefined, 'Cost')).toBeUndefined()
  })

  it('does not mutate the incoming map', () => {
    const errors = { Cost: { sessionId: 's1', message: 'a' } }
    pollCleared(errors, 'Cost')
    expect(errors.Cost).toBeDefined()
  })
})

describe('tabError (#233)', () => {
  const errors = { Cost: { sessionId: 's1', message: 'boom' } }

  it('returns the message for the matching session', () => {
    expect(tabError(errors, 'Cost', 's1')).toBe('boom')
  })

  it('hides a failure from another session', () => {
    // The bug this guards: session A's failure rendered under session B.
    expect(tabError(errors, 'Cost', 's2')).toBeNull()
  })

  it('hides a session failure on the no-session screen, and vice versa', () => {
    expect(tabError(errors, 'Cost', null)).toBeNull()
    const anon = pollFailure(undefined, 'Config', null, new Error('offline'))
    expect(tabError(anon, 'Config', 's1')).toBeNull()
    expect(tabError(anon, 'Config', null)).toBe('offline')
  })

  it('returns null for a tab with no failure', () => {
    expect(tabError(errors, 'MCP', 's1')).toBeNull()
    expect(tabError(undefined, 'Cost', 's1')).toBeNull()
  })
})
