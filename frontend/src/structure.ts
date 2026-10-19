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
// #100: pure seam for the Graph tab's project-structure view — flattens the
// /structure payload into rows the UI renders 1:1.
export interface StructureFile {
  path: string
  lines?: number
  symbols?: { kind: string; name: string; line?: number }[]
}

export interface StructureRow {
  path: string
  lines: number | undefined
  kind: string | undefined
  name: string | undefined
}

export function structureRows(data: { files?: StructureFile[] } | undefined): StructureRow[] {
  const rows: StructureRow[] = []
  for (const f of data?.files ?? []) {
    for (const s of f.symbols ?? [undefined as never]) {
      rows.push({ path: f.path, lines: f.lines, kind: s?.kind, name: s?.name })
    }
  }
  return rows
}
