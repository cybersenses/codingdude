"""Serialization of pydantic-ai message history for Session persistence."""

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter


def encode_messages(messages: list[ModelMessage]) -> str:
    return ModelMessagesTypeAdapter.dump_json(messages).decode('utf-8')


def decode_messages(payloads: list[str]) -> list[ModelMessage]:
    return [
        m for payload in payloads for m in ModelMessagesTypeAdapter.validate_json(payload)
    ]
