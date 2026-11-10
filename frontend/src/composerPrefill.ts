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
// R85 #317 (REQ-7): composer prefill seam — the exported store setter the
// tech design names. Prompt.jsx registers its text setter on mount; any
// panel (WireframeView implement buttons) can prefill without prop-drilling
// through the dock. Registration is exclusive: the mounted composer wins.
export type PrefillFn = (text: string) => void

let setter: PrefillFn | null = null

export function registerComposerPrefill(fn: PrefillFn | null): void {
  setter = fn
}

/** Returns false when no composer is mounted — callers decide whether to care. */
export function prefillComposer(text: string): boolean {
  if (!setter) return false
  setter(text)
  return true
}

/** REQ-7 template: the handoff directive the agent reads as its spec. */
export function implementPrompt(screenTitle: string, packTitle: string, artifactId: string): string {
  return `Implement the "${screenTitle}" screen from wireframe pack "${packTitle}" (${artifactId}); treat that artifact as the spec.`
}
