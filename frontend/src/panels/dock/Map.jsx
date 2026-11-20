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
import React, { useCallback, useEffect, useState } from 'react'
import { call } from '../../api'

// R103 #377: the architecture map gets its own surface instead of an artifact
// card, and the reason is mechanical rather than aesthetic. floorplan's page is
// a JavaScript app — 2.6 MB with the ELK layout engine and the fonts inlined so
// it loads nothing and works offline — while the Artifacts viewer runs every
// artifact under `sandbox=""`, scripts disabled. The map cannot render there,
// and loosening that shared viewer to `allow-scripts` would hand script
// execution to every artifact ever emitted, including chat-authored HTML.
//
// So the frame below declares its own sandbox: `allow-scripts` and
// deliberately NOT `allow-same-origin`. Without same-origin the document gets
// an opaque origin, so the page cannot touch this app's DOM, localStorage or
// session cookie even though it runs its own scripts. `map.test.ts` pins both
// halves of that: adding `allow-same-origin` later "to make a fetch work" is
// the regression the test exists to stop.
const SANDBOX = 'allow-scripts'

/** The page the server serves for one session's built map (#377). */
export function mapSrc(sessionId) {
  return `/api/sessions/${sessionId}/map`
}

/**
 * Presentational half: everything below the fetch, so the sandbox attribute is
 * assertable without a browser or a live server.
 */
export function MapView({ sessionId, state, nonce = 0, onRefresh }) {
  if (!state) {
    return (
      <div data-map="checking" className="p-2 text-xs opacity-60">
        checking for a map…
      </div>
    )
  }
  if (!state.built) {
    return (
      <div data-map="empty" className="flex h-full flex-col gap-2 p-3 text-xs">
        <p className="opacity-80">{state.reason}</p>
        <button
          type="button"
          data-map="recheck"
          onClick={onRefresh}
          className="self-start rounded border border-white/20 px-2 py-1 hover:bg-white/10"
        >
          Check again
        </button>
      </div>
    )
  }
  return (
    <div data-map="built" className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-white/10 px-2 py-1 text-[11px]">
        <span className="truncate opacity-60">
          {state.path} · {Math.round((state.bytes || 0) / 1024)} KB
        </span>
        <button
          type="button"
          data-map="refresh"
          onClick={onRefresh}
          className="ml-auto rounded border border-white/20 px-2 py-0.5 hover:bg-white/10"
        >
          Refresh
        </button>
      </div>
      <iframe
        key={nonce}
        data-map="frame"
        title="Architecture map"
        src={`${mapSrc(sessionId)}?v=${nonce}`}
        sandbox={SANDBOX}
        className="h-full min-h-0 w-full flex-1 border-0 bg-white"
      />
    </div>
  )
}

/** The panel body: one poll of the state, then the frame. */
export function Map({ sessionId }) {
  const [state, setState] = useState(null)
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)

  const load = useCallback(async () => {
    if (!sessionId) return
    try {
      const next = await call(`/sessions/${sessionId}/map/state`)
      setState(next)
      setError('')
    } catch (e) {
      // The route answers 404 for an unknown session and 200 with `built:false`
      // for a project that simply has no map; anything thrown here is a real
      // transport/auth failure, so it is shown rather than swallowed.
      setError(String((e && e.message) || e))
    }
  }, [sessionId])

  useEffect(() => {
    load()
  }, [load])

  function refresh() {
    load()
    setNonce((n) => n + 1)
  }

  if (error) {
    return (
      <div data-map="error" className="p-2 text-xs text-red-400">
        {error}
      </div>
    )
  }
  return <MapView sessionId={sessionId} state={state} nonce={nonce} onRefresh={refresh} />
}
