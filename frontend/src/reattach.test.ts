import { describe, expect, it } from 'vitest'
import { runToReattach } from './reattach'

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
