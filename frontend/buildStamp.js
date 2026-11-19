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
// #364: the build stamp must not claim more than it knows.
//
// `git rev-parse --short HEAD` reports the last commit, not the source that
// was compiled: a bundle built while the working tree held uncommitted code
// still called itself a clean build of that commit, and the footer then
// presented that label as if it identified the running code. The `-dirty`
// suffix is what makes those two states distinguishable on screen.
//
// The failure path stamps 'unknown' rather than an empty string: a blank
// footer segment reads as "no information", which is not what "git was
// unavailable" means.

import { execSync } from 'node:child_process'

const GIT_OPTS = { stdio: ['ignore', 'pipe', 'ignore'] }

/**
 * @param {(cmd: string, opts?: object) => Buffer|string} exec injected for
 *   tests; defaults to child_process.execSync.
 * @returns {string} `<sha>`, `<sha>-dirty`, or `unknown`.
 */
export function gitSha(exec = execSync) {
  try {
    const sha = exec('git rev-parse --short HEAD', GIT_OPTS).toString().trim()
    if (!sha) {
      console.warn('[build] git rev-parse returned nothing — stamping "unknown"')
      return 'unknown'
    }
    const dirty = exec('git status --porcelain', GIT_OPTS).toString().trim()
    return dirty ? `${sha}-dirty` : sha
  } catch (error) {
    console.warn(`[build] git unavailable (${error.message}) — stamping "unknown"`)
    return 'unknown'
  }
}
