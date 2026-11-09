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
// #307 (R81): composer model picker — the send contract between the picker
// state and POST /runs. The picker holds '' (default), a configured slot key
// ('main' | 'subagent' | 'fallback' | 'vision'), or a free-typed literal
// `provider:model` string. One function decides what rides on the wire so
// App.send and the picker's honest labeling can never disagree.
import type { ModelsInfo } from './api'

export interface ModelSend {
  /** The `model` string for POST /runs; null = let the server use its default. */
  send: string | null
  /** True when the string is passed through verbatim (not a resolved alias). */
  literal: boolean
  /** What the UI shows the user will actually be sent. */
  label: string
}

const DEFAULT: ModelSend = { send: null, literal: false, label: 'default (main)' }

export function resolveModelSend(
  models: ModelsInfo | null, selected: string,
): ModelSend {
  if (!selected) return { ...DEFAULT }
  // A slot alias only counts when it resolves to a non-empty configured
  // name; a null slot (stale persisted key) falls back to the default —
  // the raw key would crash the worker's model resolution.
  const resolved = models?.models[selected]
  if (resolved) return { send: resolved, literal: false, label: `${selected} — ${resolved}` }
  // A key the lineup knows but cannot resolve (null slot, stale persisted
  // selection) is NOT a literal: 'vision' as a raw model name would crash
  // the worker's model resolution. The default is the safe send.
  if (!models || selected in models.models) return { ...DEFAULT }
  return { send: selected, literal: true, label: selected }
}

/** Datalist quick options: every configured slot with an honest
 * `slot — model` label. Null slots are not selectable aliases. */
export function modelOptions(
  models: ModelsInfo | null,
): Array<{ value: string; label: string }> {
  if (!models) return []
  return Object.entries(models.models)
    .filter((entry): entry is [string, string] => Boolean(entry[1]))
    .map(([k, v]) => ({ value: k, label: `${k} — ${v}` }))
}
