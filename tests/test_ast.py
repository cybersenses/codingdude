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
"""Engine seam: AST tools — find_definition / find_references via tree-sitter."""


from helpers import scripted
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
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
            if isinstance(p, (ToolReturnPart, RetryPromptPart, TextPart))
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
    (workdir / 'notes.xyz').write_text('main = 42')
    outcome = await engine.run(
        prompt='find main in the notes file',
        workdir=workdir,
        model=call_tool_then_answer(
            'find_definition',
            {'symbol': 'main', 'path': 'notes.xyz'},
            lambda text: (
                'graceful' if 'python' in text.lower() or 'unsupported' in text.lower() else text[:200]
            ),
        ),
    )
    assert outcome.output == 'graceful'
