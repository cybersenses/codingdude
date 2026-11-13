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
import { describe, expect, it } from 'vitest'
import { buildAnswers, clearPendingPrompts, normalizeAskQuestions } from './askUser'

const qs = [
  { question: 'Which database?', options: ['postgres', 'sqlite'] },
  { question: 'Which stacks?', options: ['react', 'vue'], multi: true },
  { question: 'Project name?', options: [] },
]

describe('buildAnswers', () => {
  it('picks the selected radio option', () => {
    expect(buildAnswers(qs, { 'Which database?': 'sqlite' }, {})).toEqual({
      'Which database?': 'sqlite',
      'Which stacks?': [],
      'Project name?': '',
    })
  })

  it('collects multi-select answers as a list', () => {
    expect(buildAnswers(qs, { 'Which stacks?': ['react', 'vue'] }, {})).toEqual({
      'Which database?': '',
      'Which stacks?': ['react', 'vue'],
      'Project name?': '',
    })
  })

  it('free-text question passes the typed value through', () => {
    expect(buildAnswers(qs, {}, { 'Project name?': 'Steroids' })).toEqual({
      'Which database?': '',
      'Which stacks?': [],
      'Project name?': 'Steroids',
    })
  })

  it('Other… text overrides a radio pick', () => {
    expect(
      buildAnswers(qs, { 'Which database?': 'postgres' }, { 'Which database?': 'cockroachdb' }),
    ).toEqual({
      'Which database?': 'cockroachdb',
      'Which stacks?': [],
      'Project name?': '',
    })
  })

  it('Other… text is ignored when empty', () => {
    expect(
      buildAnswers(qs, { 'Which database?': 'postgres' }, { 'Which database?': '  ' }),
    ).toEqual({
      'Which database?': 'postgres',
      'Which stacks?': [],
      'Project name?': '',
    })
  })
})

describe('clearPendingPrompts (#145)', () => {
  const msgs = [
    { role: 'user', text: 'hi' },
    { role: 'assistant', text: '', ask: { questions: [{ question: 'Q?' }] }, gate: 'rm -rf' },
    { role: 'assistant', text: 'done', ask: null },
  ]
  it('strips ask and gate from every message, without mutating input', () => {
    const out = clearPendingPrompts(msgs)
    expect(out.every((m) => m.ask === null && m.gate === null)).toBe(true)
    expect(msgs[1].ask).not.toBeNull() // input untouched
    expect(out[2].text).toBe('done')
  })
})

// R90 #336: the ask_user tool takes one opaque JSON string, so malformed
// payloads reached render verbatim; an option object in JSX child position
// crashed the whole app with React #31. Both payloads below are verbatim
// from the persisted traces (e46a1498… run 3-yOHDkANqA, bad8698a… run YFg9GBe6sh0).
describe('normalizeAskQuestions (#336)', () => {
  const tracePayloadA = [
    {
      question: 'What should I do with the steampunk + dino theme?',
      options: [{ multi: false }, { multi: false }, { multi: false }, { multi: false }],
    },
  ]
  const tracePayloadB = [
    {
      question: 'How do you want to fix the reporting quality?',
      options: [
        { multi: true, options: ['Always-on answer-structure block ...'] },
        { multi: true },
        { multi: false },
        { multi: false },
      ],
      multi: true,
    },
  ]

  it('renders the object-options trace payload without any non-string child', () => {
    const out = normalizeAskQuestions(tracePayloadA)
    expect(out).toHaveLength(1)
    expect(out[0].question).toBe('What should I do with the steampunk + dino theme?')
    expect(out[0].options).toEqual([
      '(unlabelled option)',
      '(unlabelled option)',
      '(unlabelled option)',
      '(unlabelled option)',
    ])
    expect(out[0].multi).toBe(false)
    // React #31 came from an object in child position — nothing may survive as one
    expect(out[0].options?.every((o) => typeof o === 'string')).toBe(true)
  })

  it('normalizes the nested-options trace payload and keeps multi', () => {
    const out = normalizeAskQuestions(tracePayloadB)
    expect(out).toHaveLength(1)
    expect(out[0].question).toBe('How do you want to fix the reporting quality?')
    expect(out[0].options).toEqual([
      '(unlabelled option)',
      '(unlabelled option)',
      '(unlabelled option)',
      '(unlabelled option)',
    ])
    expect(out[0].multi).toBe(true)
  })

  it('passes well-formed questions through with defaults filled', () => {
    const out = normalizeAskQuestions([
      { question: 'Which database?', options: ['postgres', 'sqlite'] },
      { question: 'Free text?' },
    ])
    expect(out).toEqual([
      { question: 'Which database?', options: ['postgres', 'sqlite'], multi: false },
      { question: 'Free text?', options: [], multi: false },
    ])
  })

  it('drops garbage entries and survives non-array input', () => {
    expect(normalizeAskQuestions([null, 42, { noQuestion: true }, { question: 'ok' }]))
      .toEqual([{ question: 'ok', options: [], multi: false }])
    expect(normalizeAskQuestions(undefined)).toEqual([])
    expect(normalizeAskQuestions({ question: 'not an array' })).toEqual([])
  })
})
