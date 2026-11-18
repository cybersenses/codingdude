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
// R100: the two rules with real consequences — how a run's spans group into a
// trace, and when the trace dot may claim recording is happening.
import { describe, expect, it } from 'vitest'

import { groupSpansByTrace, spanKind, traceSwitchState } from './otelView'
import type { OtelStatus } from './otelView'

const status = (over: Partial<OtelStatus> = {}): OtelStatus => ({
  config_enabled: false,
  otlp_endpoint: 'http://127.0.0.1:4318',
  collector_reachable: true,
  viewer_endpoint: 'http://127.0.0.1:8000',
  viewer_reachable: true,
  viewer_error: null,
  ...over,
})

describe('spanKind', () => {
  it('names the kind from the span name pydantic-ai emits', () => {
    expect(spanKind('chat deepseek-flash')).toBe('model')
    expect(spanKind('execute_tool shell')).toBe('tool')
    expect(spanKind('invoke_agent compaction')).toBe('agent')
    expect(spanKind('send server/discover')).toBe('other')
  })
})

describe('groupSpansByTrace', () => {
  it('groups by trace_id and reads each trace top-down', () => {
    const groups = groupSpansByTrace([
      { trace_id: 'a', name: 'execute_tool shell' },
      { trace_id: 'a', name: 'chat m' },
      { trace_id: 'b', name: 'chat m' },
    ])
    expect(groups.map((g) => g.id)).toEqual(['a', 'b'])
    // The API answers newest-first, so within a trace the oldest span is first.
    expect(groups[0].spans.map((s) => s.name)).toEqual(['chat m', 'execute_tool shell'])
  })

  it('totals tokens and cost per trace, treating missing values as zero', () => {
    const [group] = groupSpansByTrace([
      { trace_id: 'a', name: 'chat m', input_tokens: 100, cost_usd: 0.5 },
      { trace_id: 'a', name: 'execute_tool shell' },
      { trace_id: 'a', name: 'chat m', input_tokens: 20, cost_usd: 0.25 },
    ])
    expect(group.inputTokens).toBe(120)
    expect(group.cost).toBeCloseTo(0.75)
  })

  it('survives an absent payload (viewer down before the first read)', () => {
    expect(groupSpansByTrace(null)).toEqual([])
    expect(groupSpansByTrace(undefined)).toEqual([])
  })
})

describe('traceSwitchState', () => {
  it('follows the config default until the browser makes a choice', () => {
    expect(traceSwitchState(null, status({ config_enabled: false })).on).toBe(false)
    expect(traceSwitchState(null, status({ config_enabled: true })).on).toBe(true)
  })

  it('lets an explicit choice beat the config either way', () => {
    expect(traceSwitchState(false, status({ config_enabled: true })).on).toBe(false)
    expect(traceSwitchState(true, status({ config_enabled: false })).on).toBe(true)
  })

  it('greys the dot only when recording is off', () => {
    expect(traceSwitchState(false, status({ collector_reachable: true })).dot)
      .toBe('bg-neutral-600')
  })

  it('warns instead of claiming success when nothing will store the spans', () => {
    const state = traceSwitchState(true, status({ collector_reachable: false }))
    expect(state.dot).toBe('bg-warning')
    expect(state.detail).toContain('dropped')
    expect(state.detail).toContain('4318')
  })

  it('is green only when the collector leg is actually reachable', () => {
    expect(traceSwitchState(true, status({ collector_reachable: true })).dot)
      .toBe('bg-success')
  })

  it('says so when the status call has not answered yet', () => {
    const state = traceSwitchState(true, null)
    expect(state.detail).toBe('collector state unknown')
    expect(state.dot).toBe('bg-warning')
  })

  it('never claims "off" while nothing has said which setting applies', () => {
    // No choice in this browser and no answer from /telemetry/status: the
    // server's [telemetry] setting decides, so "off" here would be a claim the
    // code cannot support - a run can record while the row says it is not.
    const state = traceSwitchState(null, null)
    expect(state.on).toBe(false)
    expect(state.label.startsWith('unknown:')).toBe(true)
    expect(state.detail).toContain('config decides')
  })
})
