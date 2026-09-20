import { describe, expect, it } from 'vitest'

import { checklistPrompt, checklistTitle } from './checklists'

const MD = [
  '# QA & Testing Checklist',
  '',
  'As of: 2026-09-20',
  '',
  'Use when: building test suites, verifying agent output.',
  '',
  '## Checklist',
  '',
  '- [ ] Default status is "NEEDS WORK"',
  '- [ ] Every bug fix adds the regression test',
].join('\n')

describe('checklistTitle', () => {
  it('extracts the H1 without the word Checklist', () => {
    expect(checklistTitle(MD)).toBe('QA & Testing')
  })

  it('falls back to the raw first line', () => {
    expect(checklistTitle('# Deploy')).toBe('Deploy')
  })
})

describe('checklistPrompt', () => {
  it('builds a scoped review prompt with target and checklist body', () => {
    const p = checklistPrompt('qa-testing', MD, 'Audit the auth module in src/auth/')
    expect(p).toContain('qa-testing')
    expect(p).toContain('Audit the auth module in src/auth/')
    expect(p).toContain('Default status is "NEEDS WORK"')
    expect(p).toContain('NEEDS WORK, PARTIAL, PASS')
  })

  it('works without a target (whole project)', () => {
    const p = checklistPrompt('qa-testing', MD, '')
    expect(p).toContain('the project as a whole')
    expect(p).not.toContain('null')
  })
})
