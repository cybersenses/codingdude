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
import { buildSpans } from './waterfall'

const ev = (type: string, ts: string, extra: Record<string, unknown> = {}) => ({
  type,
  ts,
  ...extra,
})

describe('buildSpans', () => {
  it('pairs TOOL_CALL_START/END into a span', () => {
    const spans = buildSpans([
      ev('RUN_STARTED', '2025-09-19T10:00:00Z'),
      ev('TOOL_CALL_START', '2025-09-19T10:00:01Z', { tool_name: 'edit_file' }),
      ev('TOOL_CALL_END', '2025-09-19T10:00:03Z', { tool_name: 'edit_file' }),
    ])
    expect(spans.spans).toHaveLength(1)
    expect(spans.spans[0]).toMatchObject({ kind: 'tool', label: 'edit_file', start: 1, end: 3 })
  })

  it('produces zero relative offsets from the first event', () => {
    const spans = buildSpans([
      ev('TOOL_CALL_START', '2025-09-19T10:00:10Z', { tool_name: 'x' }),
      ev('TOOL_CALL_END', '2025-09-19T10:00:15Z', { tool_name: 'x' }),
    ])
    expect(spans.spans[0]).toMatchObject({ start: 0, end: 5 })
  })

  it('closes an unclosed span at the last event time', () => {
    const spans = buildSpans([
      ev('TOOL_CALL_START', '2025-09-19T10:00:00Z', { tool_name: 'stuck' }),
      ev('TEXT_MESSAGE_START', '2025-09-19T10:00:08Z'),
    ])
    expect(spans.spans[0]).toMatchObject({ label: 'stuck', start: 0, end: 8, unclosed: true })
  })

  it('pairs nested delegations independently (same-name tool interleaving)', () => {
    const spans = buildSpans([
      ev('TOOL_CALL_START', '2025-09-19T10:00:00Z', { tool_name: 'a' }),
      ev('TOOL_CALL_START', '2025-09-19T10:00:01Z', { tool_name: 'b' }),
      ev('TOOL_CALL_END', '2025-09-19T10:00:02Z', { tool_name: 'b' }),
      ev('TOOL_CALL_END', '2025-09-19T10:00:04Z', { tool_name: 'a' }),
    ])
    expect(spans.spans).toEqual([
      expect.objectContaining({ label: 'a', start: 0, end: 4 }),
      expect.objectContaining({ label: 'b', start: 1, end: 2 }),
    ])
  })

  it('renders instant events (markers) as zero-length spans with kind', () => {
    const spans = buildSpans([
      ev('RUN_STARTED', '2025-09-19T10:00:00Z'),
      ev('EDIT_APPLIED', '2025-09-19T10:00:02Z', { path: 'a.py' }),
      ev('GATE_REQUEST', '2025-09-19T10:00:04Z'),
    ])
    expect(spans.spans).toEqual([
      expect.objectContaining({ kind: 'edit', label: 'a.py', start: 2, end: 2 }),
      expect.objectContaining({ kind: 'gate', label: 'GATE_REQUEST', start: 4, end: 4 }),
    ])
  })

  it('skips events with no ts', () => {
    const spans = buildSpans([ev('RUN_STARTED', ''), ev('TOOL_CALL_START', '2025-09-19T10:00:00Z', { tool_name: 'x' }), ev('TOOL_CALL_END', '2025-09-19T10:00:01Z', { tool_name: 'x' })])
    expect(spans.spans).toHaveLength(1)
    expect(spans.total).toBe(1)
  })
})
