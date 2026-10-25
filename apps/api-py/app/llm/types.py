"""Shared chat message type (ported from apps/api/src/llm/types.ts)."""

from dataclasses import dataclass
from typing import Literal, TypedDict


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


@dataclass
class GenerationResult:
    """Everything a caller needs about one generate() call: the answer text,
    plus Stage 7 "production concerns" telemetry (which provider/model
    actually answered, token counts, latency, a rough cost estimate, and
    whether automatic cross-provider fallback kicked in)."""

    content: str
    provider: Literal["ollama", "cloud"]
    model: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    estimated_cost: float | None
    fallback_used: bool = False
    fallback_from: Literal["ollama", "cloud"] | None = None
