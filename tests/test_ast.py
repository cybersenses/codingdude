"""Engine seam: AST tools — find_definition / find_references via tree-sitter."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from helpers import scripted

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)


def make_multi_file_workdir(workdir):
    src = workdir / 'src'
    src.mkdir(exist_ok=True)
    (src / 'greet.py').write_text(
        'def greet(name):\n    return f"hello {name}"\n'
    )
    (src / 'app.py').write_text(
        'from greet import greet\n\n'
        'def run():\n'
        '    message = greet("world")\n'
        '    return message\n'
    )
    # A decoy: the word "greet" appears in a docstring, grep finds it, AST shouldn't count it as a call.
    (src / 'docs.py').write_text('"""greet is documented here"""\n')


def call_tool_then_answer(tool_name: str, args: dict, check):
    def fn(messages: list[ModelMessage], info):
        if not any(isinstance(p, ToolCallPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=args)])
        returns = [
            str(p.content)
            for m in messages
            for p in m.parts
            if isinstance(p, (ToolReturnPart, TextPart))
        ]
        return ModelResponse(parts=[TextPart(content=check('\n'.join(returns)))])

    return scripted(fn)


async def test_find_definition_lands_on_def(engine, workdir):
    make_multi_file_workdir(workdir)
    outcome = await engine.run(
        prompt='where is greet defined?',
        workdir=workdir,
        model=call_tool_then_answer(
            'find_definition',
            {'symbol': 'greet'},
            lambda text: (
                'on-def' if 'greet.py:1' in text and 'definition' in text.lower() else text[:200]
            ),
        ),
    )
    assert outcome.output == 'on-def'


async def test_find_references_across_files_excludes_definition_and_docstring(engine, workdir):
    make_multi_file_workdir(workdir)
    outcome = await engine.run(
        prompt='who calls greet?',
        workdir=workdir,
        model=call_tool_then_answer(
            'find_references',
            {'symbol': 'greet'},
            lambda text: (
                'the-import-and-call'
                if 'app.py:1' in text and 'app.py:4' in text and 'docs.py' not in text
                else text[:300]
            ),
        ),
    )
    assert outcome.output == 'the-import-and-call'


async def test_unsupported_language_degrades_gracefully(engine, workdir):
    (workdir / 'notes.rs').write_text('fn main() { println!("greet"); }')
    outcome = await engine.run(
        prompt='find greet in the rust file',
        workdir=workdir,
        model=call_tool_then_answer(
            'find_definition',
            {'symbol': 'main', 'path': 'notes.rs'},
            lambda text: (
                'graceful' if 'python' in text.lower() or 'unsupported' in text.lower() else text[:200]
            ),
        ),
    )
    assert outcome.output == 'graceful'
