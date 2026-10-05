{"name": "webapp-testing", "description": "Toolkit for testing local web applications with Playwright: boot the dev server via scripts/with_server.py, drive pages, assert on DOM/network, and capture screenshots. This is the renderer that ss-verify requires for its visual gate; use it whenever a UI must be actually rendered and inspected.", "triggers": ["webapp testing", "playwright", "e2e test", "screenshot the app", "test the ui in a browser", "browser test"]}

# Web Application Testing

To test local web applications, write native Python Playwright scripts.

**Helper Scripts Available (resolve the script path from the Skill directory line in this skill's load_skill response; it is never relative to the project)**:
- `$HOME/.codingdude/skills/webapp-testing/scripts/with_server.py` - Manages server lifecycle (supports multiple servers). **Absolute path — the script lives in this skill directory, never in the project.**

**Always run scripts with `--help` first** to see usage. DO NOT read the source until you try running the script first and find that a customized solution is abslutely necessary. These scripts can be very large and thus pollute your context window. They exist to be called directly as black-box scripts rather than ingested into your context window.

## Decision Tree: Choosing Your Approach

```
User task → Is it static HTML?
    ├─ Yes → Read HTML file directly to identify selectors
    │         ├─ Success → Write Playwright script using selectors
    │         └─ Fails/Incomplete → Treat as dynamic (below)
    │
    └─ No (dynamic webapp) → Is the server already running?
        ├─ No → Run: python $HOME/.codingdude/skills/webapp-testing/scripts/with_server.py --help
        │        Then use the helper + write simplified Playwright script
        │
        └─ Yes → Reconnaissance-then-action:
            1. Navigate and wait for networkidle
            2. Take screenshot or inspect DOM
            3. Identify selectors from rendered state
            4. Execute actions with discovered selectors
```

## Example: Using with_server.py

To start a server, run `--help` first, then use the helper:

**Single server:**
```bash
python $HOME/.codingdude/skills/webapp-testing/scripts/with_server.py --server "npm run dev" --port 5173 -- python your_automation.py
```

**Multiple servers (e.g., backend + frontend):**
```bash
python $HOME/.codingdude/skills/webapp-testing/scripts/with_server.py \
  --server "cd backend && python server.py" --port 3000 \
  --server "cd frontend && npm run dev" --port 5173 \
  -- python your_automation.py
```

To create an automation script, include only Playwright logic (servers are managed automatically):
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True) # Always launch chromium in headless mode
    page = browser.new_page()
    page.goto('http://localhost:5173') # Server already running and ready
    page.wait_for_load_state('networkidle') # CRITICAL: Wait for JS to execute
    # ... your automation logic
    browser.close()
```

## Reconnaissance-Then-Action Pattern

1. **Inspect rendered DOM**:
   ```python
   page.screenshot(path='/tmp/inspect.png', full_page=True)
   content = page.content()
   page.locator('button').all()
   ```

2. **Identify selectors** from inspection results

3. **Execute actions** using discovered selectors

## Common Pitfall

❌ **Don't** inspect the DOM before waiting for `networkidle` on dynamic apps
✅ **Do** wait for `page.wait_for_load_state('networkidle')` before inspection

## Best Practices

- **Use bundled scripts as black boxes** - To accomplish a task, consider whether one of the scripts available in `scripts/` can help. These scripts handle common, complex workflows reliably without cluttering the context window. Use `--help` to see usage, then invoke directly. 
- Use `sync_playwright()` for synchronous scripts
- Always close the browser when done
- Use descriptive selectors: `text=`, `role=`, CSS selectors, or IDs
- Add appropriate waits: `page.wait_for_selector()` or `page.wait_for_timeout()`

## Reference Files

- **examples/** - Examples showing common patterns:
  - `element_discovery.py` - Discovering buttons, links, and inputs on a page
  - `static_html_automation.py` - Using file:// URLs for local HTML
  - `console_logging.py` - Capturing console logs during automation


## Scope in the CodingDude skill ecosystem

- This is **the renderer** for the ecosystem's visual gates: `ss-verify` requires a real screenshot — use this skill's Playwright approach and `scripts/with_server.py` to boot the dev server and capture it. Never claim a visual pass without a screenshot.
- Shell commands run through CodingDude's approval-gated shell tool.
- Functional assertions here complement (not replace) `ss-score` (code gate) and `ss-verify` (pixel gate): this skill answers "does it work", those answer "is it good".
- CodingDude routes screenshots to its vision model — make sure the PNG actually reaches the model before judging it.

> Adapted from anthropics/skills (Apache-2.0), license companion included.
