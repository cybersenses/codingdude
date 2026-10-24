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
import React, { useState } from 'react'
import { login } from '../api'
import logoUrl from '../assets/logo.png'

// R59 P0: moved verbatim out of App.jsx.
export function Login({ onLoggedIn }) {
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  return (
    <div className="flex h-screen items-center justify-center bg-neutral-900">
      <form
        className="w-80 rounded-lg border border-neutral-800 bg-neutral-950 p-6"
        onSubmit={async (e) => {
          e.preventDefault()
          setErr('')
          try {
            await login(password)
            onLoggedIn()
          } catch {
            setErr('wrong password')
          }
        }}
      >
        <div className="mb-4 flex items-center justify-center gap-2">
          <img src={logoUrl} alt="CodingDude logo" className="h-10 w-10 rounded" />
          <h1 className="text-center text-lg font-bold text-brand-400">CodingDude</h1>
        </div>
        <input
          type="password"
          className="mb-3 w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
        />
        {err && <div className="mb-2 text-xs text-danger">{err}</div>}
        <button className="w-full rounded bg-brand-700 px-3 py-2 text-sm font-medium text-brand-fg hover:bg-brand-600">
          Log in
        </button>
      </form>
    </div>
  )
}
