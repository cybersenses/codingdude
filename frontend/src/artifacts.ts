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
// #189: pure seam — which artifacts still need the user's attention?
// Choice cards and spec blocks are actionable (pick / edit); html, qa and
// decision artifacts are passive. Server order (newest first), capped so a
// chatty run cannot flood the chat column.
export interface Artifact {
  id: string
  kind: string
  title: string
  status: string
  payload: Record<string, unknown>
  response?: Record<string, unknown> | null
}

const ACTIONABLE = new Set(['choice', 'spec'])
const MAX_INLINE = 3

export function pendingArtifacts(items: Artifact[]): Artifact[] {
  return items
    .filter((a) => a.status === 'pending' && ACTIONABLE.has(a.kind))
    .slice(0, MAX_INLINE)
}
