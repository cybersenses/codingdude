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

    return FunctionModel(fn, stream_function=stream_fn, model_name='scripted')
