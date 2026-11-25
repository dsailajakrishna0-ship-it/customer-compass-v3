"""Tool calling with LangChain, observed through LangChain's own callback handler.

A `BaseCallbackHandler` is handed to the agent in the run's config; LangChain calls it when a chat
model starts and ends, when a tool starts, ends or fails. The handler turns those calls into the
shared observation events (names, counts and durations only). Decisions and measurements:
docs/adr/0040.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from lab_common.observed import CURRENT, ObservedMixin, offered_names
from lab_common.telemetry import ObservedRequest
from langchain_core.callbacks import BaseCallbackHandler
from tool_calling_with_langchain import LangChainToolChat


def millis_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class ObservationHandler(BaseCallbackHandler):
    def __init__(self, request: ObservedRequest, model_name: str) -> None:
        self._request = request
        self._model = model_name
        self._model_started: dict[UUID, float] = {}
        self._tool_started: dict[UUID, tuple[str, float]] = {}
        self.tools_seen: list[str] = []

    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self._model_started[run_id] = time.monotonic()

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        usage = getattr(response.generations[0][0].message, "usage_metadata", None) or {}
        started = self._model_started.pop(run_id, time.monotonic())
        self._request.model_call(
            self._model,
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            millis_since(started),
            "ok",
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._model_started.pop(run_id, time.monotonic())
        self._request.model_call(self._model, None, None, millis_since(started), "error")

    def on_tool_start(
        self, serialized: dict[str, Any], input_str: str, *, run_id: UUID, **kwargs: Any
    ) -> None:
        name = serialized.get("name") or kwargs.get("name") or "unknown"
        self._tool_started[run_id] = (name, time.monotonic())
        self.tools_seen.append(name)

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        name, started = self._tool_started.pop(run_id, ("unknown", time.monotonic()))
        self._request.tool_call(name, "ran", millis_since(started))

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        name, started = self._tool_started.pop(run_id, ("unknown", time.monotonic()))
        outcome = "invalid_arguments" if type(error).__name__ == "ValidationError" else "tool_error"
        self._request.tool_call(name, outcome, millis_since(started))


class ObservedLangChainToolChat(ObservedMixin, LangChainToolChat):
    def _invoke(self, agent: Any, payload: Any) -> Any:
        current = CURRENT.get()
        if current is None:
            return super()._invoke(agent, payload)
        request, model_name = current
        handler = ObservationHandler(request, model_name)
        state = agent.invoke(payload, config={"callbacks": [handler]})
        # A call to a tool that does not exist never reaches the callbacks (measured), so it is
        # found by comparing what the model asked for with what the callbacks saw.
        offered = offered_names(self._tools)
        asked = [
            c["name"] for m in state["messages"] if hasattr(m, "tool_calls") for c in m.tool_calls
        ]
        for name in asked:
            if name not in offered:
                request.tool_call("unknown", "invalid_call", 0)
        return state
