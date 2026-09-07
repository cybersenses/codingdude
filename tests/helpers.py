"""Shared scripted-model builders for engine-seam tests."""

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel


def say(text: str):
    def fn(messages, info):
        return ModelResponse(parts=[TextPart(content=text)])

    return fn


def scripted(fn) -> FunctionModel:
    """A FunctionModel from a sync responder, with a matching stream function."""

    async def stream_fn(messages, info):
        response = fn(messages, info)
        for part in response.parts:
            if hasattr(part, 'content') and isinstance(part.content, str):
                yield part.content
                return

    return FunctionModel(fn, stream_function=stream_fn, model_name='scripted')
