"""Shared scripted-model builders for engine-seam tests."""

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel


def say(text: str):
    def fn(messages, info):
        return ModelResponse(parts=[TextPart(content=text)])

    return fn


def scripted(fn) -> FunctionModel:
    return FunctionModel(fn, model_name='scripted')
