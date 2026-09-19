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
