import { describe, expect, it } from 'vitest'
import { describeProcess, mergeProcesses, type ProcessEntry } from './processes'

const p = (over: Partial<ProcessEntry>): ProcessEntry => ({
  pid: 1,
  command: 'bash -c pytest',
  started_at: '2026-01-01T00:00:00',
  status: 'running',
  exit_code: null,
  background: false,
  ...over,
})

describe('mergeProcesses', () => {
  it('adopts server rows and marks state changes', () => {
    const existing = [p({ pid: 1, status: 'running' })]
    const fetched = [
      p({ pid: 2, started_at: 'T2' }),
      p({ pid: 1, status: 'exited', exit_code: 0 }),
    ]
    const merged = mergeProcesses(existing, fetched)
    expect(merged.map((x) => x.pid)).toEqual([2, 1])
    expect(merged[1].status).toBe('exited')
  })

  it('never drops a row that was already seen (tracked until closed)', () => {
    const existing = [p({ pid: 7, started_at: 'T7', status: 'running' })]
    const merged = mergeProcesses(existing, [])
    expect(merged).toHaveLength(1)
    expect(merged[0].pid).toBe(7)
  })
})

describe('describeProcess', () => {
  it('summarizes pid, state and truncated command', () => {
    const line = describeProcess(p({ pid: 42, command: 'x'.repeat(200) }))
    expect(line).toMatch(/^\[42\] running — x{77}…$/)
  })
  it('shows exit code when finished', () => {
    expect(describeProcess(p({ status: 'exited', exit_code: 1 }))).toContain('exited (1)')
  })
})
