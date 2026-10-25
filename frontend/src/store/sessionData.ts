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
// R59 P2 (tech design #1 §4.3): the single data layer for dock panels.
//
// Today each dock tab runs its own 4s poll, started on tab switch. With a
// dockable workspace many panels are live at once, so naive porting means
// fifteen concurrent polls per open session. Instead: one scheduler loop
// (default 2s tick) fetches ONLY the (topic, session) keys that have at
// least one subscriber that is currently visible, pauses entirely while the
// document is hidden, and captures per-key errors in the snapshot so a
// failed fetch renders as a failure (the #231/#234 bug class) instead of
// looking like "no data yet".
//
// The store is deliberately framework-free so it unit-tests under fake
// timers; the React binding is the `useSessionData` hook at the bottom.

export type SessionId = string | null

export interface Snapshot<T = unknown> {
  /** Last successfully fetched payload. Retained across failures so a panel
   * can keep showing stale data beside its error banner. */
  data?: T
  /** Last failure as a string (errMsg-shaped). `null` after a success. */
  error: string | null
}

interface KeyState {
  snapshot: Snapshot
  subscribers: Set<() => void>
  /** Number of subscribers currently marked visible. Zero means docked-hidden:
   *  mounted (renderer:'always') but not worth polling. */
  visible: number
  inFlight: boolean
}

export type TopicFetcher = (sessionId: SessionId) => Promise<unknown>

export interface SessionStore {
  subscribe(topic: string, sessionId: SessionId, cb: () => void): () => void
  getSnapshot(topic: string, sessionId: SessionId): Snapshot
  /** Declare the visibility of one subscriber (dockview onDidVisibilityChange).
   *  `true` on subscribe by default — a plain visible subscriber needs no call. */
  setVisible(topic: string, sessionId: SessionId, visible: boolean): void
  /** Fetch one key now, out of band with the tick — after a mutation the
   *  panel owns (e.g. an MCP enable/disable), so the UI does not wait 2s. */
  refresh(topic: string, sessionId: SessionId): void
  dispose(): void
}

export interface StoreOptions {
  /** Tick interval in ms (default 2000). */
  intervalMs?: number
  /** Hidden-document probe; defaults to the DOM. */
  isHidden?: () => boolean
}

function keyOf(topic: string, sessionId: SessionId): string {
  return `${sessionId ?? '_'}:${topic}`
}

export function createSessionStore(
  fetchers: Record<string, TopicFetcher>,
  opts: StoreOptions = {},
): SessionStore {
  const intervalMs = opts.intervalMs ?? 2000
  const isHidden = opts.isHidden ?? (() => typeof document !== 'undefined' && document.hidden)
  const keys = new Map<string, KeyState>()

  function state(topic: string, sessionId: SessionId): KeyState {
    const k = keyOf(topic, sessionId)
    let s = keys.get(k)
    if (!s) {
      s = { snapshot: { error: null }, subscribers: new Set(), visible: 0, inFlight: false }
      keys.set(k, s)
    }
    return s
  }

  function emit(s: KeyState) {
    for (const cb of s.subscribers) cb()
  }

  async function fetchKey(topic: string, sessionId: SessionId, s: KeyState) {
    const fetcher = fetchers[topic]
    if (!fetcher || s.inFlight) return
    s.inFlight = true
    try {
      const data = await fetcher(sessionId)
      s.snapshot = { data, error: null }
    } catch (err) {
      // Keep the last data; a failed refresh is not "no data".
      s.snapshot = { ...s.snapshot, error: err instanceof Error ? err.message : String(err) }
    } finally {
      s.inFlight = false
      emit(s)
    }
  }

  function tick() {
    if (isHidden()) return
    for (const [k, s] of keys) {
      if (s.subscribers.size === 0 || s.visible === 0) continue
      const idx = k.indexOf(':')
      fetchKey(k.slice(idx + 1), k.slice(0, idx) === '_' ? null : k.slice(0, idx), s)
    }
  }

  const timer = setInterval(tick, intervalMs)

  return {
    subscribe(topic, sessionId, cb) {
      const s = state(topic, sessionId)
      const first = s.subscribers.size === 0
      s.subscribers.add(cb)
      s.visible += 1
      // Classic panels polled the moment they mounted; a subscriber that only
      // waits for the next tick stares at "loading…" for up to intervalMs.
      if (first && !isHidden()) fetchKey(topic, sessionId, s)
      return () => {
        s.subscribers.delete(cb)
        s.visible = Math.max(0, s.visible - 1)
      }
    },
    getSnapshot(topic, sessionId) {
      return state(topic, sessionId).snapshot
    },
    setVisible(topic, sessionId, visible) {
      const s = state(topic, sessionId)
      s.visible = Math.max(0, s.visible + (visible ? 1 : -1))
    },
    refresh(topic, sessionId) {
      fetchKey(topic, sessionId, state(topic, sessionId))
    },
    dispose() {
      clearInterval(timer)
      keys.clear()
    },
  }
}

// React binding: subscribes with useSyncExternalStore so concurrent
// subscriptions to the same key share one snapshot identity (no render loop).
// The subscribe closure must be STABLE across renders — a fresh arrow each
// render makes React resubscribe on every render, which (with mount-parity
// fetching) turned one subscription into a fetch-per-render storm.
import { useCallback, useSyncExternalStore } from 'react'

export function useSessionData(
  store: SessionStore,
  topic: string,
  sessionId: SessionId,
): Snapshot {
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(topic, sessionId, cb),
    [store, topic, sessionId],
  )
  const getSnapshot = useCallback(
    () => store.getSnapshot(topic, sessionId),
    [store, topic, sessionId],
  )
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}
