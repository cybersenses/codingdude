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
