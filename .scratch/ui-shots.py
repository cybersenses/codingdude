"""Screenshot the running CodingDude UI in both themes (pixel gate helper)."""
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path('.scratch')
OUT.mkdir(exist_ok=True)
BASE = 'http://127.0.0.1:8765'

msgs: list[str] = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.on('console', lambda m: msgs.append(f'{m.type}: {m.text}'))
    page.on('pageerror', lambda e: msgs.append(f'pageerror: {e}'))
    page.goto(BASE, wait_until='networkidle')
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / 'ui-dark.png'))

    page.evaluate('localStorage.setItem("cd-theme","light")')
    page.reload(wait_until='networkidle')
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / 'ui-light.png'))

    title = page.title()
    theme = page.evaluate('document.documentElement.dataset.theme')
    browser.close()

print('title:', title)
print('data-theme after reload:', theme)
print('dark png bytes:', (OUT / 'ui-dark.png').stat().st_size)
print('light png bytes:', (OUT / 'ui-light.png').stat().st_size)
print('--- console (last 15) ---')
print('\n'.join(msgs[-15:]) or '(none)')
