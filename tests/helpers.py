# CodingDude — a personal coding agent.
# Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Shared scripted-model builders for engine-seam tests."""

import ast
from pathlib import Path

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel


def say(text: str):
    def fn(messages, info):
        return ModelResponse(parts=[TextPart(content=text)])

    return fn


def scripted(fn) -> FunctionModel:
    """A FunctionModel from a sync responder, with a matching stream function
    (stream paths must be able to express tool calls too)."""

    async def stream_fn(messages, info):
        response = fn(messages, info)
        for i, part in enumerate(response.parts):
            if hasattr(part, 'tool_name'):
                from pydantic_ai.models.function import DeltaToolCall

                args = part.args
                if not isinstance(args, str):
                    import json

                    args = json.dumps(args)
                yield {i: DeltaToolCall(name=part.tool_name, json_args=args)}
            elif hasattr(part, 'content') and isinstance(part.content, str):
                yield part.content

    return FunctionModel(fn, stream_function=stream_fn, model_name='scripted')


# --- adoption guards -------------------------------------------------------
# One matcher for every "every Agent(...) construction must pass X" guard
# (capabilities= in test_agent_caps, name= in test_tracing). A bare
# `node.func.id == 'Agent'` test — the shape both guards started with — is
# blind to `pydantic_ai.Agent(...)`, `pai.Agent(...)` and an aliased import, so
# the very drift the guard exists to catch would sail through it.
# `test_the_agent_matcher_sees_every_construction_form` pins that it does not.

_AGENT_MODULE_PREFIX = 'pydantic_ai'


def agent_aliases(tree: ast.AST) -> set[str]:
    """Local names that resolve to pydantic-ai's `Agent` in one module."""
    names = {'Agent'}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith(
            _AGENT_MODULE_PREFIX
        ):
            for alias in node.names:
                if alias.name == 'Agent':
                    names.add(alias.asname or 'Agent')
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.name or '').startswith(_AGENT_MODULE_PREFIX):
                    # `import pydantic_ai as pai` → `pai.Agent`
                    names.add(f'{alias.asname or alias.name.split(".")[0]}.Agent')
    return names


def agent_call_nodes(tree: ast.AST) -> list[ast.Call]:
    """Every `Agent(...)` call in a module, however it was imported."""
    aliases = agent_aliases(tree)
    dotted = {a for a in aliases if '.' in a}
    plain = {a for a in aliases if '.' not in a}
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, 'id', None)
        if name in plain:
            found.append(node)
            continue
        if isinstance(func, ast.Attribute) and func.attr == 'Agent':
            # pydantic_ai.Agent, pai.Agent, and any module's .Agent
            found.append(node)
            continue
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if f'{func.value.id}.{func.attr}' in dotted:
                found.append(node)
    return found


def agent_calls_missing(keyword: str, root: Path | str = 'src/codingdude') -> list[str]:
    """`Agent(...)` call sites under `root` that omit (or blank) `keyword=`.

    A blank `name=''`/`name=None` counts as missing: the guard's job is an
    attributable span, and an empty name is not one.
    """
    offenders: list[str] = []
    for path in sorted(Path(root).rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in agent_call_nodes(tree):
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            value = keywords.get(keyword)
            if value is None:
                offenders.append(f'{path.as_posix()}:{node.lineno}')
            elif keyword == 'name' and isinstance(value, ast.Constant) and not value.value:
                offenders.append(f'{path.as_posix()}:{node.lineno}')
    return offenders
