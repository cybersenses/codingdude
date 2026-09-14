# Spec: Z.AI Vision MCP server (`zai-vision`)

## Goal
Wire the GLM coding-plan vision MCP server (`@z_ai/mcp-server`) into CodingDude's
existing MCP infrastructure so the agent gains OCR, UI-diff, diagram-understanding
and video tools — using the same ZAI key already configured via `providers.zai`.

## Non-goals
- No change to native `inspect_image` (vision.py): it stays the workdir-scoped,
  trace-integrated (`IMAGE_INSPECTED`) pixel-gate path. MCP vision tools are
  complementary (OCR / ui_diff_check / diagrams / video), not a replacement.
- No new tool code — this is a config-seed change only.

## Design
### mcp.json entry (`zai-vision`)
```json
{
  "type": "stdio",
  "command": "cmd", "args": ["/c", "npx", "-y", "@z_ai/mcp-server@latest"],
  "env": {"Z_AI_API_KEY": "${ZAI_API_KEY:-}", "Z_AI_MODE": "ZAI"}
}
```
- pydantic-ai `load_mcp_toolsets` expands `${VAR:-default}` at load time; the key
  is referenced, never stored in the file. `apply_provider_keys` already sets
  `ZAI_API_KEY` from `providers.zai` (env wins over config, as today).
- MCP SDK merges per-server `env` over a safe default environment
  (PATH/APPDATA/... inherited on Windows), so `npx` resolves.
- Empty key default: server fails at connect; the MCP pre-flight drops failed
  servers with a warning — the run proceeds, matching existing behavior.
- `command` is resolved at seed time via `shutil.which('npx')` with the same
  `.cmd`/`.bat` → `cmd /c` wrapping used for codegraph (Windows spawn rule).
  If npx is absent, the zai-vision entry is not seeded (same rule as codegraph).

### ensure_default_mcp becomes additive
Current contract: never touch an existing mcp.json. New contract:
- Missing file → seed all available defaults (unchanged).
- Existing file → add any *known default* server whose name is absent;
  never modify or remove existing entries; preserve file shape.

## Tests (tests/test_mcp.py)
1. Fresh home without npx/codegraph → no zai-vision seeded.
2. Fresh home with a fake npx on PATH → zai-vision seeded with env expansion
   placeholder and Z_AI_MODE=ZAI.
3. Existing mcp.json containing codegraph + a custom server → zai-vision added,
   codegraph and custom entry byte-identical.
4. Existing mcp.json already containing zai-vision (any shape) → file untouched.
5. `load_merged_mcp_toolsets` / expansion: env referenced via `${ZAI_API_KEY:-}`
   resolves from process env (covered indirectly by pydantic-ai; assert our
   seeded string contains the expansion token).

## Verification
- pytest, ruff, mypy green.
- Live spawn (real npx + key) is a user-side smoke check on next run; the
  pre-flight warning path makes a broken install non-fatal.
