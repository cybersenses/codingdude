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
"""Serialization of pydantic-ai message history for Session persistence."""

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter


def encode_messages(messages: list[ModelMessage]) -> str:
    """Serialize message history to the JSON wire format stored per session."""
    return ModelMessagesTypeAdapter.dump_json(messages).decode('utf-8')


def decode_messages(payloads: list[str]) -> list[ModelMessage]:
    """Deserialize stored JSON back into message history objects."""
    return [
        m for payload in payloads for m in ModelMessagesTypeAdapter.validate_json(payload)
    ]


def sanitize_history(messages: list) -> list:
    """Drop dangling tool calls that a stopped/crashed run left behind.

    A run interrupted mid-tool persists an assistant message with tool calls
    but no results. Feeding that back as history makes the model refuse new
    prompts, so we trim the trailing incomplete exchange. The user prompt that
    preceded it is kept as context.
    """
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
    )

    cleaned = list(messages)
    changed = True
    while changed and cleaned:
        changed = False
        last = cleaned[-1]

        # 1. Response with tool calls and no result yet → drop it.
        if isinstance(last, ModelResponse) and any(
            isinstance(p, ToolCallPart) for p in last.parts
        ):
            cleaned.pop()
            changed = True
            continue

        # 2. Trailing tool-returns with no answer after them → the exchange was
        #    interrupted; drop the orphan results.
        if isinstance(last, ModelRequest) and any(
            isinstance(p, ToolReturnPart) for p in last.parts
        ):
            cleaned.pop()
            changed = True
            continue

    return cleaned
