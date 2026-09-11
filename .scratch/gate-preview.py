"""Render the rebuilt ApprovalCard + ToolTimeline with the real built CSS."""
import glob
import pathlib
from playwright.sync_api import sync_playwright

css = sorted(glob.glob('frontend/dist/assets/index-*.css'))[-1]

html = f'''<!doctype html><html data-theme="dark"><head><meta charset="utf-8">
<link rel="stylesheet" href="../{css}"></head>
<body class="bg-canvas text-ink p-8">
<div style="max-width:780px" class="space-y-4">
  <div class="my-2 overflow-hidden rounded-lg border border-warning/50 bg-surface">
    <div class="flex items-center gap-2 border-b border-line bg-warning/10 px-3 py-2">
      <span class="h-1.5 w-1.5 rounded-full bg-warning"></span>
      <span class="text-xs font-semibold text-warning">Approval needed</span>
      <span class="ml-auto text-[11px] text-ink-muted">nothing runs until you decide</span>
    </div>
    <pre class="overflow-x-auto border-b border-line bg-canvas px-3 py-2 font-mono text-xs text-ink">git push --dry-run origin main</pre>
    <div class="flex items-center gap-2 px-3 py-2">
      <button class="rounded bg-brand px-3 py-1.5 text-xs font-medium text-brand-fg hover:bg-brand-hover">Approve once</button>
      <button class="rounded border border-line px-3 py-1.5 text-xs text-ink-muted hover:text-ink">Approve all matching</button>
      <button class="ml-auto rounded border border-danger/50 px-3 py-1.5 text-xs text-danger hover:bg-danger/10">Deny</button>
    </div>
  </div>
  <div class="my-1 overflow-hidden rounded border border-line bg-surface/60 text-xs">
    <button class="flex w-full items-center gap-2 px-2 py-1 text-left text-ink-muted hover:text-ink">
      <span>&#9662;</span><span>3 tool calls</span>
      <span class="ml-auto font-mono text-[10px] text-ink-muted/70">shell</span>
    </button>
    <div class="space-y-1 border-t border-line px-2 py-2">
      <div class="rounded bg-canvas p-1.5 font-mono text-[11px]"><div class="text-accent">read_file</div><pre class="whitespace-pre-wrap text-ink-muted">src/app.py: 42 lines</pre></div>
      <div class="rounded bg-canvas p-1.5 font-mono text-[11px]"><div class="text-accent">grep</div><pre class="whitespace-pre-wrap text-ink-muted">3 matches in 2 files</pre></div>
      <div class="rounded bg-canvas p-1.5 font-mono text-[11px]"><div class="text-accent">shell</div><pre class="whitespace-pre-wrap text-ink-muted">exit 0</pre></div>
    </div>
  </div>
</div></body></html>'''

preview = pathlib.Path('.scratch/gate-preview.html')
preview.write_text(html, encoding='utf-8')
url = 'file:///' + str(preview.resolve()).replace('\\', '/')

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 900, 'height': 460})
    page.goto(url)
    page.wait_for_timeout(400)
    page.screenshot(path='.scratch/gate-dark.png')
    page.evaluate('document.documentElement.dataset.theme="light"')
    page.wait_for_timeout(300)
    page.screenshot(path='.scratch/gate-light.png')
    browser.close()

print('css:', css)
print('gate-dark.png bytes:', pathlib.Path('.scratch/gate-dark.png').stat().st_size)
print('gate-light.png bytes:', pathlib.Path('.scratch/gate-light.png').stat().st_size)
