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
