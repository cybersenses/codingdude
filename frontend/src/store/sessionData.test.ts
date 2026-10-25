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
// R59 P2 (tech design #1 §4.3): the visibility-gated data store. One
// scheduler loop per browser; on each tick it fetches only topics that have
// at least one visible subscriber, pauses entirely while the document is
// hidden, and captures per-topic errors in the snapshot so a failed fetch can
// never masquerade as "no data yet" (the #231/#234 bug class).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSessionStore } from './sessionData'

function fetchers(spec) {
  return Object.fromEntries(
    Object.entries(spec).map(([topic, impl]) => [topic, vi.fn(impl)]),
  )
}

describe('sessionData store', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('fetches a subscribed visible topic on each tick', async () => {
    const f = fetchers({ diff: async () => ({ diff: 'x' }) })
    const store = createSessionStore(f)
    const cb = vi.fn()
    store.subscribe('diff', 's1', cb)
    await vi.advanceTimersByTimeAsync(2000)
    expect(f.diff).toHaveBeenCalledWith('s1')
    await vi.advanceTimersByTimeAsync(2000)
    expect(f.diff.mock.calls.length).toBeGreaterThanOrEqual(2)
    store.dispose()
  })

  it('never fetches a topic with no subscribers', async () => {
    const f = fetchers({ cost: async () => ({}) })
    const store = createSessionStore(f)
    await vi.advanceTimersByTimeAsync(6000)
    expect(f.cost).not.toHaveBeenCalled()
    store.dispose()
  })

  it('stops fetching once the last subscriber unsubscribes', async () => {
    const f = fetchers({ diff: async () => ({}) })
    const store = createSessionStore(f)
    const off = store.subscribe('diff', 's1', vi.fn())
    await vi.advanceTimersByTimeAsync(2000)
    expect(f.diff.mock.calls.length).toBeGreaterThanOrEqual(1)
    off()
    const calls = f.diff.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000)
    expect(f.diff.mock.calls.length).toBe(calls)
    store.dispose()
  })

  it('pauses entirely while the document is hidden', async () => {
    const f = fetchers({ diff: async () => ({}) })
    let hidden = true
    const store = createSessionStore(f, { isHidden: () => hidden })
    store.subscribe('diff', 's1', vi.fn())
    await vi.advanceTimersByTimeAsync(6000)
    expect(f.diff).not.toHaveBeenCalled()
    hidden = false
    await vi.advanceTimersByTimeAsync(2000)
    expect(f.diff).toHaveBeenCalled()
    store.dispose()
  })

  it('skips a topic whose subscribers are all dock-hidden after mount', async () => {
    const f = fetchers({ diff: async () => ({}) })
    const store = createSessionStore(f)
    store.subscribe('diff', 's1', vi.fn())
    // Subscribe fetches once immediately (mount parity with the classic poll);
    // dock-hiding must stop the *ticks*, not retroactively cancel it.
    await vi.advanceTimersByTimeAsync(0)
    expect(f.diff).toHaveBeenCalledTimes(1)
    store.setVisible('diff', 's1', false)
    await vi.advanceTimersByTimeAsync(6000)
    expect(f.diff).toHaveBeenCalledTimes(1)
    store.setVisible('diff', 's1', true)
    await vi.advanceTimersByTimeAsync(2000)
    expect(f.diff).toHaveBeenCalledTimes(2)
    store.dispose()
  })

  it('captures a fetch error in the snapshot and keeps the last data', async () => {
    let fail = false
    const f = fetchers({
      diff: async () => {
        if (fail) throw new Error('boom')
        return { diff: 'good' }
      },
    })
    const store = createSessionStore(f)
    const cb = vi.fn()
    store.subscribe('diff', 's1', cb)
    await vi.advanceTimersByTimeAsync(2000)
    expect(store.getSnapshot('diff', 's1')).toEqual({ data: { diff: 'good' }, error: null })
    fail = true
    await vi.advanceTimersByTimeAsync(2000)
    const snap = store.getSnapshot('diff', 's1')
    expect(snap.error).toBe('boom')
    expect(snap.data).toEqual({ diff: 'good' })
    store.dispose()
  })

  it('notifies subscribers when the snapshot changes', async () => {
    const f = fetchers({ diff: async () => ({ n: 1 }) })
    const store = createSessionStore(f)
    const cb = vi.fn()
    store.subscribe('diff', 's1', cb)
    await vi.advanceTimersByTimeAsync(2000)
    expect(cb).toHaveBeenCalled()
    store.dispose()
  })

  it('fetches the same topic for two sessions independently', async () => {
    const f = fetchers({ diff: async (sid) => ({ sid }) })
    const store = createSessionStore(f)
    store.subscribe('diff', 's1', vi.fn())
    store.subscribe('diff', 's2', vi.fn())
    await vi.advanceTimersByTimeAsync(2000)
    expect(store.getSnapshot('diff', 's1').data).toEqual({ sid: 's1' })
    expect(store.getSnapshot('diff', 's2').data).toEqual({ sid: 's2' })
    store.dispose()
  })

  it('a session-independent topic passes a null session to its fetcher', async () => {
    const f = fetchers({ config: async (sid) => ({ sid }) })
    const store = createSessionStore(f)
    store.subscribe('config', null, vi.fn())
    await vi.advanceTimersByTimeAsync(2000)
    expect(f.config).toHaveBeenCalledWith(null)
    store.dispose()
  })

  it('does not refetch while a fetch for the same key is in flight', async () => {
    let resolve
    const f = fetchers({
      diff: () => new Promise((r) => { resolve = r }),
    })
    const store = createSessionStore(f)
    store.subscribe('diff', 's1', vi.fn())
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(2000)
    expect(f.diff).toHaveBeenCalledTimes(1)
    resolve({})
    await vi.advanceTimersByTimeAsync(2000)
    expect(f.diff).toHaveBeenCalledTimes(2)
    store.dispose()
  })

  it('fetches immediately on the first subscribe, not at the next tick', async () => {
    const f = fetchers({ cost: async () => ({ n: 1 }) })
    const store = createSessionStore(f)
    store.subscribe('cost', 's1', vi.fn())
    await vi.advanceTimersByTimeAsync(0)
    expect(f.cost).toHaveBeenCalledTimes(1)
    store.dispose()
  })

  it('refresh() fetches immediately, out of band with the tick', async () => {
    const f = fetchers({ mcp: async () => ({ n: 1 }) })
    const store = createSessionStore(f)
    store.subscribe('mcp', 's1', vi.fn())
    await vi.advanceTimersByTimeAsync(0)
    expect(f.mcp).toHaveBeenCalledTimes(1) // the mount-parity subscribe fetch
    store.refresh('mcp', 's1')
    await vi.advanceTimersByTimeAsync(0)
    expect(f.mcp).toHaveBeenCalledTimes(2)
    store.dispose()
  })
})
