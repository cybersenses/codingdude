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
// #364: a stamp that cannot distinguish a clean build from a dirty one lies
// about provenance. These pin the four states the build can be in.
import { afterEach, describe, expect, it, vi } from 'vitest'

import { gitSha } from './buildStamp'

const SHA = 'abc1234'

/** A fake git: answers rev-parse and status, records what was asked. */
function fakeGit({ sha = SHA, status = '', failOn = null } = {}) {
  const calls = []
  const exec = (cmd) => {
    calls.push(cmd)
    if (failOn && cmd.includes(failOn)) throw new Error('git: command not found')
    return Buffer.from(cmd.includes('--porcelain') ? status : sha)
  }
  return { exec, calls }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('gitSha', () => {
  it('stamps the bare commit when the tree is clean', () => {
    const { exec } = fakeGit()
    expect(gitSha(exec)).toBe(SHA)
  })

  it('marks a build made from a dirty tree', () => {
    const { exec } = fakeGit({ status: ' M frontend/src/ui.jsx\n' })
    expect(gitSha(exec)).toBe(`${SHA}-dirty`)
  })

  it('asks git about the working tree, not just for the commit', () => {
    // Guards the wiring: a stamp that only ran rev-parse would pass the clean
    // case above while still being unable to report a dirty build.
    const { exec, calls } = fakeGit()
    gitSha(exec)
    expect(calls).toHaveLength(2)
    expect(calls[1]).toContain('status --porcelain')
  })

  it('says "unknown" instead of blanking when git cannot be run', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(gitSha(fakeGit({ failOn: 'rev-parse' }).exec)).toBe('unknown')
    expect(warn).toHaveBeenCalled()
  })

  it('says "unknown" when git answers with nothing', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(gitSha(fakeGit({ sha: '' }).exec)).toBe('unknown')
    expect(warn).toHaveBeenCalled()
  })
})
