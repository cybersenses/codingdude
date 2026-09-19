import { describe, expect, it } from 'vitest'
import { groupEventsByRun, pickRunId, type TraceEvent } from './runs'

const ev = (run_id: string | undefined, type: string, ts = '2026-09-19T12:00:00'): TraceEvent => ({
  run_id,
  type,
  ts,
})

describe('groupEventsByRun', () => {
  it('groups events by run_id preserving in-run order', () => {
    const groups = groupEventsByRun([
      ev('a', 'RUN_STARTED'),
      ev('b', 'RUN_STARTED'),
      ev('a', 'TOOL_CALL_END'),
      ev(undefined, 'LEGACY'),
    ])
    expect(Object.keys(groups)).toEqual(['a', 'b', '(unattributed)'])
    expect(groups['a'].map((e) => e.type)).toEqual(['RUN_STARTED', 'TOOL_CALL_END'])
    expect(groups['(unattributed)']).toHaveLength(1)
  })

  it('returns empty object for no events', () => {
    expect(groupEventsByRun([])).toEqual({})
  })
})

describe('pickRunId', () => {
  it('keeps the user selection when it still has events', () => {
    const groups = groupEventsByRun([ev('a', 'X'), ev('b', 'Y')])
    expect(pickRunId(groups, 'a')).toBe('a')
  })
  it('falls back to the first-listed run (newest in API order) otherwise', () => {
    const groups = groupEventsByRun([ev('a', 'X'), ev('b', 'Y')])
    expect(pickRunId(groups, 'gone')).toBe('a')
    expect(pickRunId(groups, null)).toBe('a')
  })
  it('returns null when there are no runs', () => {
    expect(pickRunId({}, null)).toBeNull()
  })
})
