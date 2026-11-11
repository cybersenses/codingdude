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

/** The `<select>`'s extra option for a free-typed `provider:model` literal. */
export const CUSTOM_OPTION = '__custom'

/** How classifySelection reads a persisted selection against the lineup.
 * 'default' covers both an empty selection and a lineup-known null slot
 * (a stale persisted key): both send the default. 'no-models' is a failed
 * /models fetch — the send decision is also the default, but the highlight
 * deliberately shows the persisted text as custom (R83) so it stays visible. */
export type PickClass = 'default' | 'slot' | 'literal' | 'no-models'

/** #320: the ONE classifier for a picker selection. resolveModelSend (what
 * rides the wire) and pickerSelection (what the option highlights) are two
 * faithful mappings over this — the truth is written once, so the highlight
 * can never drift from the send decision. */
export function classifySelection(models: ModelsInfo | null, selected: string): PickClass {
  if (!selected) return 'default'
  if (!models) return 'no-models'
  const resolved = models.models[selected]
  if (resolved) return 'slot'
  if (selected in models.models) return 'default' // null slot: stale persisted key
  return 'literal'
}

export function pickerSelection(models: ModelsInfo | null, selected: string): string {
  switch (classifySelection(models, selected)) {
    case 'default': return '' // null slot sends default → highlights default
    case 'slot': return selected
    case 'literal':
    case 'no-models': return CUSTOM_OPTION
  }
}

export function resolveModelSend(
  models: ModelsInfo | null, selected: string,
): ModelSend {
  // A slot alias only counts when it resolves to a non-empty configured
  // name; a null slot (stale persisted key) falls back to the default —
  // the raw key would crash the worker's model resolution. 'vision' as a
  // raw model name is not a literal.
  switch (classifySelection(models, selected)) {
    case 'default':
    case 'no-models':
      return { ...DEFAULT }
    case 'slot': {
      const resolved = models!.models[selected]
      return { send: resolved, literal: false, label: `${selected} — ${resolved}` }
    }
    case 'literal':
      return { send: selected, literal: true, label: selected }
  }
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
