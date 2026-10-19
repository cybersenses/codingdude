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
import { buildAnswers, clearPendingPrompts } from './askUser'

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
