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
// #307 (R81): the composer model picker's send contract. The picker state is
// either '' (default), a configured slot key (alias), or a free-typed
// `provider:model` literal; resolveModelSend is the single place that decides
// what actually rides on the wire and what the UI labels it as.
import { describe, expect, it } from 'vitest'
import type { ModelsInfo } from './api'
import { CUSTOM_OPTION, modelOptions, pickerSelection, resolveModelSend } from './modelpick'

const lineup: ModelsInfo = {
  default: 'main',
  models: {
    main: 'zai:glm-5.3-flash',
    subagent: 'zai:glm-5.3-flash',
    fallback: 'zai:glm-5.3-air',
    vision: null,
  },
}

describe('resolveModelSend', () => {
  it('empty selection sends null (server default = main)', () => {
    expect(resolveModelSend(lineup, '')).toEqual({
      send: null, literal: false, label: 'default (main)',
    })
  })

  it('a configured slot alias sends the configured model name', () => {
    expect(resolveModelSend(lineup, 'main')).toEqual({
      send: 'zai:glm-5.3-flash', literal: false, label: 'main — zai:glm-5.3-flash',
    })
    expect(resolveModelSend(lineup, 'fallback')!.send).toBe('zai:glm-5.3-air')
  })

  it('a null slot (stale persisted key) falls back to the default, never the raw key', () => {
    // 'vision' is not a resolvable model name — sending it verbatim would
    // crash the worker at model resolution. The safe default is null.
    expect(resolveModelSend(lineup, 'vision')).toEqual({
      send: null, literal: false, label: 'default (main)',
    })
  })

  it('an unknown key passes through as a literal provider:model string', () => {
    expect(resolveModelSend(lineup, 'openai:gpt-4o')).toEqual({
      send: 'openai:gpt-4o', literal: true, label: 'openai:gpt-4o',
    })
  })

  it('a failed /models fetch sends null — never a stale alias or typed guess', () => {
    // The picker is disabled on failure, but a persisted selection from a
    // previous session may still be set; the safe send is the default.
    expect(resolveModelSend(null, 'main')).toEqual({
      send: null, literal: false, label: 'default (main)',
    })
    expect(resolveModelSend(null, '').send).toBeNull()
  })
})

describe('modelOptions', () => {
  it('lists the configured slots with honest slot — model labels', () => {
    expect(modelOptions(lineup)).toEqual([
      { value: 'main', label: 'main — zai:glm-5.3-flash' },
      { value: 'subagent', label: 'subagent — zai:glm-5.3-flash' },
      { value: 'fallback', label: 'fallback — zai:glm-5.3-air' },
    ])
  })

  it('drops null slots and tolerates an absent payload', () => {
    expect(modelOptions(null)).toEqual([])
    expect(modelOptions({ default: 'main', models: {} })).toEqual([])
  })
})

// R83: what the composer <select> highlights. The datalist combobox it
// replaces filtered suggestions against the input's own value, so a
// persisted pick locked the dropdown to that one entry; a real select
// never filters, and pickerSelection keeps the highlight truthful to
// resolveModelSend's send decision.
describe('pickerSelection', () => {
  it('empty selection highlights the default option', () => {
    expect(pickerSelection(lineup, '')).toBe('')
  })

  it('a configured slot highlights itself', () => {
    expect(pickerSelection(lineup, 'main')).toBe('main')
    expect(pickerSelection(lineup, 'fallback')).toBe('fallback')
  })

  it('a null slot highlights the default (resolveModelSend sends the default)', () => {
    expect(pickerSelection(lineup, 'vision')).toBe('')
  })

  it('an unknown literal highlights the custom option', () => {
    expect(pickerSelection(lineup, 'openai:gpt-4o')).toBe(CUSTOM_OPTION)
  })

  it('a persisted selection with no /models payload highlights custom (text stays visible)', () => {
    expect(pickerSelection(null, 'main')).toBe(CUSTOM_OPTION)
    expect(pickerSelection(null, '')).toBe('')
  })
})

// #320: the classification cascade used to be written twice (resolveModelSend
// and pickerSelection each walked the same decision tree). Now one classifier
// decides the class; the two public functions are faithful mappings over it.
import { classifySelection } from './modelpick'

describe('classifySelection (#320: one truth, two mappings)', () => {
  it('classifies every selection shape', () => {
    expect(classifySelection(lineup, '')).toBe('default')
    expect(classifySelection(lineup, 'main')).toBe('slot')
    expect(classifySelection(lineup, 'vision')).toBe('default') // null slot folds into default
    expect(classifySelection(lineup, 'openai:gpt-4o')).toBe('literal')
    expect(classifySelection(null, 'main')).toBe('no-models')
    expect(classifySelection(null, '')).toBe('default')
  })

  it('highlight and send decision agree per class', () => {
    const cases: Array<[ModelsInfo | null, string]> = [
      [lineup, ''], [lineup, 'main'], [lineup, 'vision'],
      [lineup, 'openai:gpt-4o'], [null, 'main'], [null, ''],
    ]
    for (const [models, sel] of cases) {
      const send = resolveModelSend(models, sel)
      const highlight = pickerSelection(models, sel)
      if (send.send === null) {
        // default sends → the default option; no-models deliberately shows
        // the persisted text as custom (R83 UX choice, one named branch now).
        expect(highlight === '' || (models === null && highlight === CUSTOM_OPTION)).toBe(true)
      } else if (send.literal) {
        expect(highlight).toBe(CUSTOM_OPTION)
      } else {
        expect(highlight).toBe(sel)
      }
    }
  })
})
