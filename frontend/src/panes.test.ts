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
import { PANE_SPECS, paneWidth } from './panes'

describe('paneWidth', () => {
  it('grows the sidebar when dragging right', () => {
    expect(paneWidth('sidebar', 256, 100)).toBe(356)
  })
  it('grows the rail when dragging right (#74)', () => {
    expect(paneWidth('rail', 208, 100)).toBe(308)
  })
  it('shrinks the right panel when dragging its divider left', () => {
    expect(paneWidth('right', 384, -84)).toBe(468)
  })
  it('grows the dock when dragging its top handle up', () => {
    expect(paneWidth('dock', 240, -60)).toBe(300)
  })
  it('clamps every pane to its spec range', () => {
    expect(paneWidth('rail', 208, 1000)).toBe(PANE_SPECS.rail.max)
    expect(paneWidth('rail', 208, -1000)).toBe(PANE_SPECS.rail.min)
    expect(paneWidth('sidebar', 256, 1000)).toBe(PANE_SPECS.sidebar.max)
    expect(paneWidth('right', 384, -1000)).toBe(PANE_SPECS.right.max)
  })
})
