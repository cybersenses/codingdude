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
// #321: the config screen's lineup datalist suggestions. Before a fetch the
// datalist suggests bare provider prefixes (R84); after a successful
// GET /config/provider-models it suggests one full `provider:model` option
// per reachable model. The text input stays the single write path — these
// are suggestions only, mirroring the R84b catalog pre-fill philosophy.

/** One provider's entry from GET /config/provider-models — the JSON shape
 * of codingdude.config.list_provider_models (no secrets ride here). */
export interface ProviderModelEntry {
  configured: boolean
  ok: boolean | null
  status: number | null
  detail: string | null
  models: string[]
}

export type ProviderModels = Record<string, ProviderModelEntry>

/** The slice of the /config/models payload the suggestions read. */
export interface LineupCfg {
  provider_prefixes?: string[]
  provider_catalog?: Array<{ name: string }>
}

/** Datalist options for the lineup model fields: `provider:model-id` for
 * every listed model, a bare `provider:` prefix for each provider that
 * could not be listed (failed fetch, native, unconfigured). Sorted and
 * deduped; `fetched === null` is exactly the R84 prefix list. */
export function lineupSuggestions(
  cfg: LineupCfg, fetched: ProviderModels | null,
): string[] {
  const out = new Set<string>()
  for (const [name, e] of Object.entries(fetched ?? {})) {
    if (e.models.length === 0) {
      // Configured but unlistable (failed fetch, native): the bare prefix
      // keeps it discoverable — free-text still works against it (Q4).
      out.add(`${name}:`)
      continue
    }
    for (const id of e.models) out.add(`${name}:${id}`)
  }
  // Providers known only through the catalog/prefix list (not configured,
  // so not in the fetch) keep their bare prefix as a suggestion.
  const prefixes = new Set(cfg.provider_prefixes ?? [])
  for (const e of cfg.provider_catalog ?? []) prefixes.add(e.name)
  for (const p of prefixes) if (!fetched || !(p in fetched)) out.add(`${p}:`)
  return [...out].sort()
}

/** Terse one-line fetch status for the button's neighbor. */
export function fetchStatusText(fetched: ProviderModels | null): string | null {
  if (!fetched) return null
  const providers = Object.keys(fetched).length
  const models = Object.values(fetched)
    .reduce((n, e) => n + e.models.length, 0)
  return `${models} model${models === 1 ? '' : 's'} across ${providers} provider${providers === 1 ? '' : 's'}`
}
