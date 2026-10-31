"""Shared chat message type (ported from apps/api/src/llm/types.ts)."""

from dataclasses import dataclass, field
from typing import Literal, TypedDict


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ToolCall:
    """One tool the model asked to call. `error` is set (and `arguments` empty) when the model's
    arguments were not valid JSON, so the caller can tell the model instead of crashing."""

    id: str
    name: str
    arguments: dict
    error: str | None = None


@dataclass
class GenerationResult:
    """Everything a caller needs about one generate() call: the answer text,
    plus "production concerns" telemetry (which model actually answered,
    token counts, latency, a rough cost estimate, and whether a fallback
    model answered instead of the first choice)."""

    content: str
    model: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    estimated_cost: float | None
    fallback_used: bool = False
    # the model that was tried first and failed, when a fallback answered (None otherwise)
    fallback_from_model: str | None = None
    # tools the model asked to call instead of (or besides) answering; empty for a plain answer
    tool_calls: list[ToolCall] = field(default_factory=list)
