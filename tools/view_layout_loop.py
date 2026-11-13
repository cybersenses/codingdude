# R88 #331 — View deep-link layout loop (closed path).
#
# Repro contract (evaluator-mandated): the USER's exact saved 1920 layout,
# viewport 1920x949, Artifacts CLOSED at click time (the path that shipped
# broken: 'below nav' sidebar band + dock-wrapper auto-scroll void).
# Asserts post-fix:
#   1. dock wrapper uses overflow-clip and never scrolls (scrollTop stays 0)
#   2. Artifacts docks into the CENTER column group (x >= 300, width > 900),
#      never a narrow sidebar band
#   3. no grid shift: every group y >= 0 and the grid still reaches the
#      dock's bottom (max group bottom >= 850) — no black void
#   4. document scroll == viewport (1920x949)
#   5. debounced save keeps Artifacts inside the chat-group leaf — no
#      artifacts-only sidebar leaf persists
# Deterministic: seeded layout, one close, one click, fixed waits (~15s).
# Screenshot for the PhotoEvidence shape compare: .scratch/r88_after.png
import json
import sys

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8765'

# The user's saved layout as pasted during diagnosis (v1, preset default):
# [nav 305][chat-group(chat,config,memory,graph,artifacts) 1110][trace 1110][8-tab group 505].
USER_LAYOUT = {
    'v': 1,
    'preset': 'default',
    'layout': {
        'grid': {
            'root': {
                'type': 'branch',
                'data': [
                    {'type': 'leaf', 'data': {'views': ['nav'], 'activeView': 'nav', 'id': '6'}, 'size': 305},
                    {
                        'type': 'branch',
                        'data': [
                            {
                                'type': 'leaf',
                                'data': {
                                    'views': ['chat', 'config', 'memory', 'graph', 'artifacts'],
                                    'activeView': 'artifacts',
                                    'id': '3',
                                },
                                'size': 659,
                            },
                            {'type': 'leaf', 'data': {'views': ['trace'], 'activeView': 'trace', 'id': '1'}, 'size': 194},
                        ],
                        'size': 1110,
                    },
                    {
                        'type': 'leaf',
                        'data': {
                            'views': ['renders', 'terminal', 'processes', 'explorer', 'planning', 'waterfall', 'notes', 'output'],
                            'activeView': 'planning',
                            'id': '2',
                        },
                        'size': 505,
                    },
                ],
                'size': 853,
            },
            'width': 1920,
            'height': 853,
            'orientation': 'HORIZONTAL',
        },
        'panels': {
            'nav': {'id': 'nav', 'contentComponent': 'nav', 'title': 'Projects & sessions', 'minimumWidth': 180},
            'chat': {'id': 'chat', 'contentComponent': 'chat', 'title': 'Chat', 'renderer': 'always', 'minimumWidth': 280},
            'config': {'id': 'config', 'contentComponent': 'config', 'title': 'Config', 'renderer': 'always'},
            'memory': {'id': 'memory', 'contentComponent': 'memory', 'title': 'Memory'},
            'graph': {'id': 'graph', 'contentComponent': 'graph', 'title': 'Graph'},
            'artifacts': {'id': 'artifacts', 'contentComponent': 'artifacts', 'title': 'Artifacts', 'renderer': 'always'},
            'trace': {'id': 'trace', 'contentComponent': 'trace', 'title': 'Trace'},
            'renders': {'id': 'renders', 'contentComponent': 'renders', 'title': 'Renders', 'renderer': 'always'},
            'terminal': {'id': 'terminal', 'contentComponent': 'terminal', 'title': 'Terminal', 'renderer': 'always'},
            'processes': {'id': 'processes', 'contentComponent': 'processes', 'title': 'Processes'},
            'explorer': {'id': 'explorer', 'contentComponent': 'explorer', 'title': 'Explorer', 'minimumWidth': 140},
            'planning': {'id': 'planning', 'contentComponent': 'planning', 'title': 'Planning'},
            'waterfall': {'id': 'waterfall', 'contentComponent': 'waterfall', 'title': 'Waterfall'},
            'notes': {'id': 'notes', 'contentComponent': 'notes', 'title': 'Notes'},
            'output': {'id': 'output', 'contentComponent': 'output', 'title': 'Output'},
        },
        'activeGroup': '3',
    },
}

SEED_JS = """(layout) => {
  localStorage.setItem('cd-layout-v1', JSON.stringify(layout));
  location.reload();
}"""

PROBE_JS = """() => {
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
  };
  const groups = [...document.querySelectorAll('.dv-groupview')].map((g) => ({
    tabs: [...g.querySelectorAll('.dv-tab')].map((t) => t.textContent.trim()),
    box: box(g),
  }));
  const wrapper = document.querySelector('.min-h-0.flex-1');
  const saved = JSON.parse(localStorage.getItem('cd-layout-v1') || 'null');
  const leaves = [];
  const walk = (n) => {
    if (!n) return;
    if (n.type === 'leaf') leaves.push(n.data.views);
    if (n.type === 'branch') (n.data || []).forEach(walk);
  };
  if (saved && saved.layout) walk(saved.layout.grid.root);
  return {
    groups,
    wrapperOverflow: wrapper ? getComputedStyle(wrapper).overflow : null,
    wrapperScrollTop: wrapper ? wrapper.scrollTop : null,
    doc: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
    viewport: [window.innerWidth, window.innerHeight],
    savedLeaves: leaves,
  };
}"""


def fail(msg):
    print(f'R88 VIEW LOOP: FAIL - {msg}')
    sys.exit(1)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1920, 'height': 949})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(BASE)
    page.wait_for_load_state('load')
    page.evaluate(SEED_JS, USER_LAYOUT)
    page.wait_for_load_state('load')
    page.wait_for_timeout(4000)

    before = page.evaluate(PROBE_JS)
    if not any('Artifacts' in g['tabs'] for g in before['groups']):
        fail(f'seed sanity: Artifacts tab not open after restore: {before["groups"]}')
    print('seed: user layout restored, Artifacts open (sanity OK)')

    # CLOSED path: close the Artifacts tab, then click the chat card's View.
    page.evaluate(
        """() => {
        const tab = [...document.querySelectorAll('.dv-tab')].find((t) => t.textContent.indexOf('Artifacts') !== -1);
        const close = tab && tab.querySelector('.dv-default-tab-action');
        if (close) close.click();
    }"""
    )
    page.wait_for_timeout(600)
    page.evaluate(
        """() => {
        const chatTab = [...document.querySelectorAll('.dv-tab')].find((t) => t.textContent.indexOf('Chat') !== -1);
        if (chatTab) chatTab.click();
    }"""
    )
    page.wait_for_timeout(300)
    card = page.locator('button[data-view-artifact]').first
    try:
        card.wait_for(state='attached', timeout=10000)
    except Exception:
        fail('View button never attached')
    # The button lives inside the chat panel's render overlay; Playwright's
    # mouse click reports "outside of the viewport" against dockview's parked
    # overlay geometry, so dispatch like a real DOM click instead.
    page.evaluate("() => document.querySelector('button[data-view-artifact]').click()")
    page.wait_for_timeout(1200)

    after = page.evaluate(PROBE_JS)
    page.screenshot(path='.scratch/r88_after.png')

    if after['wrapperOverflow'] != 'clip':
        fail(f"belt: wrapper overflow={after['wrapperOverflow']}, expected clip")
    if after['wrapperScrollTop'] not in (0, None):
        fail(f"belt: wrapper scrolled (scrollTop={after['wrapperScrollTop']}) - void bug back")
    print(f"belt: overflow=clip, scrollTop={after['wrapperScrollTop']} (0 = no auto-scroll)")

    art = [g for g in after['groups'] if 'Artifacts' in g['tabs']]
    if not art:
        fail(f'Artifacts did not reopen: {after["groups"]}')
    abox = art[0]['box']
    if abox['x'] < 300 or abox['w'] < 900:
        fail(f'placement: Artifacts landed as a sidebar band {abox} (need center column: x>=300, w>900)')
    print(f'placement: Artifacts group at x={abox["x"]} w={abox["w"]} h={abox["h"]} (center column)')

    low = [g for g in after['groups'] if g['box']['y'] < 0]
    if low:
        fail(f'void: groups scrolled off-screen top: {json.dumps(low)}')
    bottoms = [g['box']['y'] + g['box']['h'] for g in after['groups']]
    if max(bottoms) < 850:
        fail(f'void: grid ends at y={max(bottoms)} (<850) - black void below')
    print(f'void: all groups y>=0, grid reaches y={max(bottoms)} (dock bottom ~919)')

    if after['doc'] != after['viewport']:
        fail(f"document scroll {after['doc']} != viewport {after['viewport']}")
    print(f"doc: {after['doc']} == viewport {after['viewport']}")

    if any(v == ['artifacts'] for v in after['savedLeaves']):
        fail(f'save: artifacts-only sidebar leaf persisted: {after["savedLeaves"]}')
    chat_leaf = [v for v in after['savedLeaves'] if 'artifacts' in v]
    print(f'save: artifacts lives in leaf {chat_leaf} (no sidebar leaf)')

    if errors:
        fail(f'page errors: {errors[:3]}')
    browser.close()
print('R88 VIEW LOOP: OK (closed path, all assertions passed)')
