"""Shared chat message type (ported from apps/api/src/llm/types.ts)."""

from dataclasses import dataclass
from typing import Literal, TypedDict


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


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
