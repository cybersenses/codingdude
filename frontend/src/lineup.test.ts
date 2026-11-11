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
// #321: the config screen's lineup datalist. Before a fetch it suggests bare
// provider prefixes (the R84 behavior); after GET /config/provider-models it
// suggests one full `provider:model` option per reachable model. The input
// stays the single write path — these are suggestions only.
import { describe, expect, it } from 'vitest'
import { lineupSuggestions, type ProviderModels } from './lineup'

const cfg = {
  provider_prefixes: ['deepseek', 'zai'],
  provider_catalog: [
    { name: 'openai', label: 'OpenAI', env_var: 'OPENAI_API_KEY', base_url: null, needs_key: true, note: '' },
  ],
}

const fetched: ProviderModels = {
  deepseek: { configured: true, ok: true, status: 200, detail: null, models: ['deepseek-v4-pro', 'deepseek-v4-flash'] },
  zai: { configured: true, ok: false, status: 0, detail: 'getaddrinfo failed', models: [] },
}

describe('lineupSuggestions', () => {
  it('no fetch yet: bare provider prefixes, exactly the R84 behavior', () => {
    expect(lineupSuggestions(cfg, null)).toEqual(['deepseek:', 'openai:', 'zai:'])
  })

  it('a provider with models expands to full provider:model options', () => {
    const out = lineupSuggestions(cfg, fetched)
    expect(out).toContain('deepseek:deepseek-v4-flash')
    expect(out).toContain('deepseek:deepseek-v4-pro')
    expect(out).not.toContain('deepseek:')
  })

  it('a failed or empty provider keeps its bare prefix', () => {
    expect(lineupSuggestions(cfg, fetched)).toContain('zai:')
  })

  it('sorted and free of duplicates', () => {
    const out = lineupSuggestions(cfg, fetched)
    expect(out).toEqual([...new Set(out)].sort())
  })

  it('a fetch with no listed providers at all degrades to prefixes', () => {
    const dead: ProviderModels = {
      anthropic: { configured: true, ok: null, status: null, detail: 'no OpenAI-compatible endpoint — not listed', models: [] },
    }
    expect(lineupSuggestions(cfg, dead)).toEqual(['anthropic:', 'deepseek:', 'openai:', 'zai:'])
  })
})
