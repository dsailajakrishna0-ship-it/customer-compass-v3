"""A scripted stand-in for a chat model, so the tests need no key and no network.

Each call to the model returns the next scripted AIMessage; `seen` keeps the messages it was given
on each call so a test can check what the framework sent.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def tool_call(name: str, args: dict[str, Any], call_id: str = "call-1") -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def ai(content: str = "", calls: Sequence[dict[str, Any]] = ()) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=list(calls),
        usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    )


class ScriptedChatModel(BaseChatModel):
    script: list[AIMessage]
    seen: list[list[BaseMessage]] = []
    tools_bound: list[str] = []
    on_call: Any = None  # called at the start of every model call (tests use it to delete or wait)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        self.tools_bound = [
            t["function"]["name"]
            if isinstance(t, dict) and "function" in t
            else getattr(t, "name", str(t))
            for t in tools
        ]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        if self.on_call is not None:
            self.on_call()
        if not self.script:
            raise AssertionError("The model was called more often than the test scripted.")
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])


def scripted(*replies: AIMessage) -> ScriptedChatModel:
    return ScriptedChatModel(script=list(replies), seen=[], tools_bound=[])
