import { describe, expect, it } from 'vitest'
import { pickPending, type TraceEvent } from './pending'

const ev = (over: Partial<TraceEvent>): TraceEvent => ({ type: 'X', ...over })

describe('pickPending', () => {
  it('returns null without a run id', () => {
    expect(pickPending([ev({ type: 'ASK_USER' })], null)).toBeNull()
  })

  it('restores an open ask', () => {
    const events = [ev({ run_id: 'r1', type: 'ASK_USER', questions: [{ question: 'q?' }] })]
    expect(pickPending(events, 'r1')).toEqual({ kind: 'ask', questions: [{ question: 'q?' }] })
  })

  it('restores an open gate', () => {
    const events = [ev({ run_id: 'r1', type: 'GATE_REQUEST', command: 'pytest -q' })]
    expect(pickPending(events, 'r1')).toEqual({ kind: 'gate', command: 'pytest -q' })
  })

  it('a resolution after the request clears the card', () => {
    const events = [
      ev({ run_id: 'r1', type: 'ASK_USER', ts: '2026-09-25T10:00:00Z' }),
      ev({ run_id: 'r1', type: 'ASK_USER_RESOLVED', ts: '2026-09-25T10:01:00Z' }),
    ]
    expect(pickPending(events, 'r1')).toBeNull()
  })

  it('orders newest-first API input by ts (request arrives after resolved in file order)', () => {
    const events = [
      ev({ run_id: 'r1', type: 'ASK_USER_RESOLVED', ts: '2026-09-25T10:01:00Z' }),
      ev({ run_id: 'r1', type: 'ASK_USER', ts: '2026-09-25T10:00:00Z' }),
    ]
    expect(pickPending(events, 'r1')).toBeNull()
  })

  it('ignores other runs and unrelated events', () => {
    const events = [
      ev({ run_id: 'r2', type: 'ASK_USER', ts: '2026-09-25T10:02:00Z' }),
      ev({ run_id: 'r1', type: 'TEXT_MESSAGE_CONTENT', ts: '2026-09-25T10:03:00Z' }),
    ]
    expect(pickPending(events, 'r1')).toBeNull()
  })
})
