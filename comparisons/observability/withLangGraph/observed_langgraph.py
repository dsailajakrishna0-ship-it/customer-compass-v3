"""Tool calling with LangGraph, observed through LangGraph's own stream of updates.

`graph.stream(..., stream_mode="updates")` yields one event per node that ran (the model node, the
tools node, the round counter, the last-answer node). The time between two events is that node's
duration; the messages in an event say which tools were asked for and how they ended. Decisions and
measurements: docs/adr/0040.
"""

from __future__ import annotations

import time
from typing import Any

from lab_common.observed import CURRENT, ObservedMixin, offered_names
from langchain_core.messages import AIMessage, ToolMessage
from tool_calling_with_langgraph import LangGraphToolChat


def arguments_are_valid(arguments: dict[str, Any]) -> bool:
    """The contract's arguments: exactly a non-empty string company_name."""
    name = arguments.get("company_name")
    return set(arguments) == {"company_name"} and isinstance(name, str) and bool(name.strip())


class ObservedLangGraphToolChat(ObservedMixin, LangGraphToolChat):
    def _run(self, graph: Any, payload: Any) -> Any:
        current = CURRENT.get()
        if current is None:
            return super()._run(graph, payload)
        request, model_name = current
        offered = offered_names(self._tools)
        messages = list(payload["messages"])
        asked: dict[str, tuple[str, dict[str, Any]]] = {}
        last = time.monotonic()
        for update in graph.stream(payload, stream_mode="updates"):
            now = time.monotonic()
            millis = int((now - last) * 1000)
            last = now
            for node, delta in update.items():
                new = list((delta or {}).get("messages", []))
                messages.extend(new)
                if node in ("model", "final_answer"):
                    for message in new:
                        if isinstance(message, AIMessage):
                            usage = message.usage_metadata or {}
                            request.model_call(
                                model_name,
                                usage.get("input_tokens"),
                                usage.get("output_tokens"),
                                millis,
                                "ok",
                            )
                            for call in message.tool_calls:
                                asked[call["id"]] = (call["name"], dict(call["args"]))
                elif node == "tools":
                    # The node ran all its tools together: its time is shared equally (measured limit
                    # of node-level events: there is no time per tool).
                    each = millis // max(1, len(new))
                    for message in new:
                        if not isinstance(message, ToolMessage):
                            continue
                        name, arguments = asked.get(message.tool_call_id, ("unknown", {}))
                        if name not in offered:
                            request.tool_call("unknown", "invalid_call", each)
                        elif message.status == "error":
                            outcome = (
                                "tool_error"
                                if arguments_are_valid(arguments)
                                else "invalid_arguments"
                            )
                            request.tool_call(name, outcome, each)
                        else:
                            request.tool_call(name, "ran", each)
        return {"messages": messages, "rounds": 0}
