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
import React from 'react'

// R59 P0: moved verbatim out of App.jsx. Last-resort boundary so a render
// crash anywhere inside the workspace shows a readable stack instead of a
// blank page — which matters more once panels are user-arranged.
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="flex h-screen items-center justify-center bg-neutral-900 p-6">
          <div className="max-w-lg rounded-lg border border-danger/60 bg-neutral-950 p-6">
            <h1 className="mb-2 text-lg font-bold text-danger">UI crashed</h1>
            <pre className="mb-4 whitespace-pre-wrap text-xs text-neutral-400">
              {this.state.error && this.state.error.stack
                ? String(this.state.error.stack)
                : String(this.state.error)}
            </pre>
            <button
              className="rounded bg-brand-700 px-3 py-1 text-sm text-brand-fg"
              onClick={() => location.reload()}
            >
              Reload
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
