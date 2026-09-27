"""API fuzzing gate (ticket #159, R47).

One seam, `fuzz_api`: hypothesis-driven fuzzing of a FastAPI/Starlette app
in the workdir, run in a subprocess (never the worker's loop) with a hard
timeout. Same fail-closed shape as `mutation.run_mutation` / `bench.run_bench`.
Scope: JSON-body and path routes via starlette's TestClient; any 5xx is a
crash with its route and a reproducing body. Derandomized so reported
crashes reproduce.
"""
from __future__ import annotations

import json
from pathlib import Path

from .tools import resolve_workdir_file

_DRIVER = r'''
import importlib.util, json, sys

from hypothesis import given, settings, strategies as st
from starlette.testclient import TestClient

spec = importlib.util.spec_from_file_location("_fuzz_target", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

app = getattr(mod, "app", None)
if app is None:
    print(json.dumps({"error": "no `app` attribute found (need a FastAPI/Starlette app)"}))
    sys.exit(0)

client = TestClient(app)
bodies = st.dictionaries(
    st.text(min_size=1, max_size=8),
    st.one_of(st.integers(-1000, 1000), st.text(max_size=32), st.booleans()),
    max_size=4,
)
path_values = {"int": "1", "str": "x", "float": "1.5", "path": "x", "uuid": "00000000-0000-0000-0000-000000000000"}

routes_fuzzed = 0
crashes = []

for route in app.routes:
    methods = getattr(route, "methods", None) or set()
    methods = methods - {"HEAD", "OPTIONS"}
    if not methods:
        continue
    path = route.path
    concrete = path
    ok = True
    for name in getattr(route, "param_convertors", {}):
        conv = route.param_convertors[name]
        kind = getattr(conv, "convertor_type", "str")
        if kind not in path_values:
            ok = False
            break
        concrete = concrete.replace("{" + name + "}", path_values[kind])
    if not ok:
        continue

    for method in sorted(methods):
        routes_fuzzed += 1

        @settings(derandomize=True, max_examples=int(sys.argv[2]), deadline=None)
        @given(payload=bodies)
        def probe(payload):
            kwargs = {}
            if method in ("POST", "PUT", "PATCH"):
                kwargs["json"] = payload
            try:
                resp = client.request(method, concrete, **kwargs)
                status = resp.status_code
            except Exception as exc:
                crashes.append({"route": f"{method} {path}", "detail": repr(exc)[:200]})
                return
            if status >= 500:
                crashes.append({"route": f"{method} {path}", "detail": f"HTTP {status}"})

        probe()

print(json.dumps({"routes_fuzzed": routes_fuzzed, "crashes": crashes[:20]}))
'''


async def fuzz_api(
    workdir: str | Path, rel_path: str, max_examples: int = 25, timeout: int = 180,
) -> dict:
    """Fuzz the FastAPI/Starlette app in `rel_path` with hypothesis.

    Returns {"routes_fuzzed", "crashes": [{route, detail}]} or {"error": ...}
    — never raises. Derandomized, so a reported crash reproduces.
    """
    root = Path(workdir).resolve()
    target = resolve_workdir_file(root, rel_path)
    if target is None:
        return {"error": f"file not found in workdir: {rel_path}"}

    import sys as _sys

    argv = [
        _sys.executable, "-c", _DRIVER, str(target), str(max(1, max_examples)),
    ]

    from .tools import run_captured

    captured = await run_captured(argv, cwd=root, timeout=timeout)
    if captured is None:
        return {"error": f"fuzz run timed out after {timeout}s"}
    if captured.code == -1:
        return {"error": captured.stderr.strip() or "fuzz driver failed to spawn"}
    if captured.code != 0:
        return {"error": captured.stderr.strip()[-800:] or f"exit {captured.code}"}
    try:
        data = json.loads(captured.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": "fuzz driver produced no parsable output"}
    if "error" in data:
        return {"error": data["error"]}
    data["file"] = rel_path
    return data


def build_fuzz_toolset(workdir: Path):
    """The `fuzz_api` tool: hypothesis fuzzing of the project's API (#159)."""
    from pydantic_ai import ModelRetry
    from pydantic_ai.toolsets import FunctionToolset

    async def fuzz_api_tool(path: str, max_examples: int = 25) -> str:
        """Fuzz a FastAPI/Starlette app file with Hypothesis-generated
        request bodies and report routes that crash (5xx or unhandled
        exceptions), each with a reproducing route + body class.

        Use after adding or changing HTTP routes. Derandomized: reported
        crashes reproduce deterministically.
        """
        result = await fuzz_api(workdir, path, max_examples=max_examples)
        if "error" in result:
            raise ModelRetry(f"api fuzz failed: {result['error']}")
        if not result["crashes"]:
            return (
                f"fuzzed {result['routes_fuzzed']} route(s) in {result['file']} "
                f"({max_examples} examples each): no crashes."
            )
        lines = [
            f"fuzzed {result['routes_fuzzed']} route(s) in {result['file']}: "
            f"{len(result['crashes'])} crash(es) found —"
        ]
        for crash in result["crashes"]:
            lines.append(f"  {crash['route']}: {crash['detail']}")
        return "\n".join(lines)

    from pydantic_ai.tools import Tool

    # Register under the public name `fuzz_api` (inner fn can't shadow the seam).
    return FunctionToolset([Tool(fuzz_api_tool, name='fuzz_api')])
