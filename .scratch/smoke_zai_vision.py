"""One-shot zai-vision MCP smoke test: apply provider keys, spawn the server
via the same pydantic-ai path the engine uses, list tools, and make one real
tool call (tiny image) to confirm end-to-end connectivity."""
import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from codingdude.config import apply_provider_keys, load_config  # noqa: E402
from codingdude.mcp_config import (  # noqa: E402
    load_merged_mcp_toolsets, merged_mcp_server_names, _find_list_tools,
)

HOME = Path(r'C:\Users\norma\.codingdude')
WORKDIR = Path(r'G:\pydantic')


class _DummyTool:
    tool_def = None


class _DummyCtx:
    tool_def = None


async def main() -> int:
    config = load_config(HOME)
    apply_provider_keys(config)

    names = merged_mcp_server_names(HOME, WORKDIR)
    print('enabled servers:', names)
    toolsets = load_merged_mcp_toolsets(HOME, WORKDIR)

    # find the zai-vision toolset
    target = None
    for name, ts in zip(names, toolsets, strict=False):
        if name == 'zai-vision':
            target = ts
    if target is None:
        print('FAIL: zai-vision toolset missing (spawn failed?)')
        return 1

    inner = _find_list_tools(target)
    # descend to the raw server object (2-arg call_tool: name, args)
    server = inner
    for value in vars(inner).values():
        if hasattr(value, 'call_tool') and not hasattr(value, '__self__'):
            server = value
            break
    print('server object:', type(server).__name__)
    async with server:
        tools = await server.list_tools()
        names_list = [t.name for t in tools]
        print('zai-vision tools:', names_list)

        # smallest possible real call: 1x1 white PNG
        png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4//8/AwAI/AL+'
            'hc2rNAAAAABJRU5ErkJggg=='
        )
        img_path = Path(r'G:\pydantic\.scratch\smoke_1x1.png')
        img_path.write_bytes(png)
        toolset_tool = next(
            (t for t in tools if t.name == 'extract_text_from_screenshot'),
            tools[0],
        )
        call_name = toolset_tool.name
        print(f'calling {call_name} ...')
        result = await server.call_tool(call_name, {
            'image_source': str(img_path),
            'prompt': 'Extract all text from this image.',
        })
        text = ''.join(
            getattr(c, 'text', '') for c in result.content
        )
        print('result:', text[:300])
    print('SMOKE OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
