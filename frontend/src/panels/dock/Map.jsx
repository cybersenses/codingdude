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

/** The build's own record, wherever the panel can show more than the frame. */
function BuildReceipt({ build }) {
  if (!build) return null
  const warnings = build.warnings || []
  if (!build.error && warnings.length === 0) return null
  // #379: verbatim, never summarised. Each warning names a field of
  // architecture.json that matched no included file, which is the only signal
  // that the authored input is wrong; an error is floorplan's own words.
  return (
    <div className="space-y-1" data-map="receipt">
      {build.error ? (
        <p data-map="build-error" className="whitespace-pre-wrap text-red-400">
          {build.error}
        </p>
      ) : null}
      {warnings.length ? (
        <ul data-map="build-warnings" className="list-disc space-y-0.5 pl-4 opacity-70">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/**
 * Presentational half: everything below the fetch, so the sandbox attribute is
 * assertable without a browser or a live server.
 */
export function MapView({
  sessionId,
  state,
  nonce = 0,
  onRefresh,
  onBuild,
  posting = false,
}) {
  if (!state) {
    return (
      <div data-map="checking" className="p-2 text-xs opacity-60">
        checking for a map…
      </div>
    )
  }
  // `running` is the server's answer, derived from the build lock: it is true
  // both while this button waits and when another tab started the build, so one
  // rule covers both and a stale "building" cannot outlive the build.
  const building = posting || state.running === true
  if (!state.built) {
    // #379: "Check again" re-asked a question whose answer could not change;
    // building is the action that can. The button is absent rather than
    // disabled when there is nothing to build with — a disabled control still
    // reads as "click me later", and the dependency needs installing first.
    const canBuild = state.available !== false
    return (
      <div data-map="empty" className="flex h-full flex-col gap-2 overflow-auto p-3 text-xs">
        <p className="opacity-80">{state.reason}</p>
        <BuildReceipt build={state.build} />
        <div className="flex gap-2">
          {canBuild ? (
            <button
              type="button"
              data-map="build"
              disabled={building}
              onClick={onBuild}
              className="self-start rounded border border-white/20 px-2 py-1 hover:bg-white/10 disabled:opacity-50"
            >
              {building ? 'building…' : 'Build map'}
            </button>
          ) : null}
          <button
            type="button"
            data-map="recheck"
            onClick={onRefresh}
            className="self-start rounded border border-white/20 px-2 py-1 hover:bg-white/10"
          >
            Check again
          </button>
        </div>
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
      {/* A built map can still carry warnings — the page drew, but an authored
          path matched nothing. Shown above the frame so it is not lost. */}
      <div className="shrink-0 px-2 py-1 text-[11px]">
        <BuildReceipt build={state.build} />
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

/** The panel body: poll the state, expose the build, then the frame. */
export function Map({ sessionId }) {
  const [state, setState] = useState(null)
  const [error, setError] = useState('')
  const [nonce, setNonce] = useState(0)
  const [posting, setPosting] = useState(false)

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

  // While a build runs the state is the only progress signal there is: the
  // route answers 200 with the receipt when the pair settles inside its budget
  // and 202 when it does not, and either way `running` (the build lock) turns
  // false when it is over. So polling follows the lock, not the request.
  useEffect(() => {
    if (state?.running !== true) return undefined
    const timer = setInterval(load, 2000)
    return () => clearInterval(timer)
  }, [state?.running, load])

  function refresh() {
    load()
    setNonce((n) => n + 1)
  }

  const build = useCallback(async () => {
    if (!sessionId || posting) return
    setPosting(true)
    try {
      const result = await call(`/sessions/${sessionId}/map/build`, { method: 'POST' })
      // The reply carries the panel's next state on both the settled (200) and
      // the still-running (202) answer; when it settled successfully the frame
      // appears without a second round trip.
      if (result.state) setState(result.state)
      if (result.ok) setNonce((n) => n + 1)
    } catch (e) {
      // 409 is another build already running for this project; anything else is
      // transport. Either way the server's message is the useful one, and the
      // poll above picks the state back up.
      setError(String((e && e.message) || e))
      load()
    } finally {
      setPosting(false)
    }
  }, [sessionId, posting, load])

  if (error) {
    return (
      <div data-map="error" className="p-2 text-xs text-red-400">
        {error}
      </div>
    )
  }
  return (
    <MapView
      sessionId={sessionId}
      state={state}
      nonce={nonce}
      onRefresh={refresh}
      onBuild={build}
      posting={posting}
    />
  )
}
