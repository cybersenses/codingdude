import { describe, expect, it } from 'vitest'
import { buildTour } from './tour'

const ev = (type: string, ts: number, extra: Record<string, unknown> = {}) => ({ type, ts, ...extra })

describe('buildTour', () => {
  it('turns tool calls and edits into ordered narrative steps', () => {
    const steps = buildTour([
      ev('RUN_STARTED', 1),
      ev('TOOL_CALL_START', 2, { tool_name: 'read_file' }),
      ev('TOOL_CALL_END', 3, { tool_name: 'read_file' }),
      ev('TOOL_CALL_START', 4, { tool_name: 'edit_file' }),
      ev('EDIT_APPLIED', 5, { path: 'src/a.py' }),
      ev('RUN_FINISHED', 6),
    ])
    expect(steps.map((s) => s.label)).toEqual([
      'run started',
      'read_file',
      'edit_file → edited src/a.py',
      'run finished',
    ])
  })

  it('ignores text-stream noise and unclosed calls wait for their end', () => {
    const steps = buildTour([
      ev('TEXT_MESSAGE_START', 1),
      ev('TEXT_MESSAGE_CONTENT', 2, { delta: 'hi' }),
      ev('TOOL_CALL_START', 3, { tool_name: 'shell' }),
      ev('TEXT_MESSAGE_END', 4),
    ])
    expect(steps.map((s) => s.label)).toEqual(['shell (running…)'])
  })

  it('accepts ISO-string timestamps (trace events)', () => {
    const steps = buildTour([
      { type: 'RUN_STARTED', ts: '2026-09-20T10:00:00Z' },
      { type: 'RUN_FINISHED', ts: '2026-09-20T10:00:05Z' },
    ])
    expect(steps.map((s) => s.label)).toEqual(['run started', 'run finished'])
  })

  it('returns empty for noise-only runs', () => {
    expect(buildTour([ev('TEXT_MESSAGE_START', 1)])).toEqual([])
  })
})
