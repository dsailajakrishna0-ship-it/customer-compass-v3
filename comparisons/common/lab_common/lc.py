"""Reading a LangChain message list: the tools that really ran, and the usage of the last reply."""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from .chat import Result, ToolUse, UnavailableError, Usage


def tools_run(messages: list[AnyMessage]) -> list[ToolUse]:
    """A tool call counts when a tool message answered it (a call the model made after the round
    limit, which nobody ran, does not)."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    return [
        ToolUse(call["name"], dict(call["args"]))
        for m in messages
        if isinstance(m, AIMessage)
        for call in m.tool_calls
        if call["id"] in answered
    ]


def read_result(messages: list[AnyMessage], model_name: str, started: float) -> Result:
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if last_ai is None:
        raise UnavailableError("The model gave no answer.")
    meta = dict(last_ai.usage_metadata or {})
    usage = Usage(
        model=model_name,
        tokens_in=meta.get("input_tokens"),
        tokens_out=meta.get("output_tokens"),
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return Result(message=str(last_ai.text), tools_used=tools_run(messages), usage=usage)


def window_messages(
    messages: list[AnyMessage], max_messages: int, max_chars: int
) -> list[AnyMessage]:
    """The window of the contract with LangChain's `trim_messages`: the most recent `max_messages`
    messages, then the oldest dropped until the history is at most `max_chars` characters. A single
    message longer than `max_chars` leaves nothing (measured)."""
    from langchain_core.messages import trim_messages

    recent = trim_messages(messages, max_tokens=max_messages, token_counter=len, strategy="last")
    return trim_messages(
        recent,
        max_tokens=max_chars,
        token_counter=lambda batch: sum(len(str(m.content)) for m in batch),
        strategy="last",
    )
