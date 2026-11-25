"""The few types every approach speaks, so the HTTP face does not care which one is behind it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Message:
    """One message of the conversation the client sends: role is user or assistant."""

    role: str
    content: str


@dataclass(frozen=True)
class ToolUse:
    """A tool the model asked for, with the arguments it was run with (the response's toolsUsed)."""

    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    """Which model answered, the tokens of the last model call and the time of the whole answer."""

    model: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int


@dataclass(frozen=True)
class Result:
    message: str
    tools_used: list[ToolUse] = field(default_factory=list)
    usage: Usage | None = None


class UnavailableError(RuntimeError):
    """The model or the CRM could not be reached or answered badly: the route answers 503."""


class ToolChat(Protocol):
    """One approach: answers a conversation, calling tools when the model asks for them."""

    approach: str
    """The approach's folder name, shown in the web app ("via withLangChain")."""

    def answer(self, messages: list[Message], model: str | None) -> Result:
        """`model` is the one the client picked, or None for the backend's own default."""
        ...
