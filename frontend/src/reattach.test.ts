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
import { SSE_MAX_RETRIES, runToReattach, sseRetryDelayMs } from './reattach'

describe('runToReattach', () => {
  const live = new Map([
    ['s1', 'run-a'],
    ['s2', 'run-b'],
  ])

  it('returns the live run of the selected session', () => {
    expect(runToReattach(live, 's1', null)).toBe('run-a')
  })

  it('returns null when the selected session has no live run', () => {
    expect(runToReattach(live, 's9', null)).toBeNull()
  })

  it('returns null when there is no selected session', () => {
    expect(runToReattach(live, null, null)).toBeNull()
  })

  it('returns null when already attached to a run', () => {
    expect(runToReattach(live, 's1', 'run-z')).toBeNull()
  })
})

// #78: a run that bounces its own server must survive a downtime window far
// longer than the old 5-attempt (~15s) budget — the worker keeps running and
// persists its outcome, so the UI should ride out the outage and settle from
// persisted messages instead of erroring while the run is still live.
describe('sseRetryDelayMs', () => {
  it('backs off linearly at first', () => {
    expect(sseRetryDelayMs(0)).toBe(1000)
    expect(sseRetryDelayMs(1)).toBe(2000)
    expect(sseRetryDelayMs(3)).toBe(4000)
  })

  it('caps the delay at 5 seconds', () => {
    expect(sseRetryDelayMs(4)).toBe(5000)
    expect(sseRetryDelayMs(29)).toBe(5000)
  })

  it('budgets at least 2 minutes of total retry time', () => {
    const total = Array.from({ length: SSE_MAX_RETRIES }, (_, a) => sseRetryDelayMs(a)).reduce((a, b) => a + b, 0)
    expect(total).toBeGreaterThanOrEqual(120_000)
  })
})
