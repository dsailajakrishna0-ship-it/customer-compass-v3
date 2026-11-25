"""Conversation memory with LangGraph: the graph's state holds the messages, the checkpointer
(`InMemorySaver`) keeps them per thread id (the conversation id), and `trim_messages` makes the
window inside the model node. The new messages travel in their own state key and join the stored
ones only when the model answered, so a failed turn stores nothing. What we add: the ids, the time
limit and the cap (`ConversationIndex`), the bound on stored messages (the thread is rewritten as one
checkpoint after each turn) and "deleted during the call stays deleted". Decisions and measurements:
docs/adr/0042.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, TypedDict

from lab_common.chat import Message, UnavailableError, Usage
from lab_common.lc import window_messages
from lab_common.memory import (
    SYSTEM_PROMPT,
    Answer,
    Conversation,
    ConversationIndex,
    Created,
    MemoryLimits,
    utc_now,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


class MemoryState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]  # what is stored
    new: list[AnyMessage]  # this turn's messages, not stored until the model answered
    used: int  # how many stored messages the window sent


def to_message(message: AnyMessage) -> Message:
    return Message(
        "user" if isinstance(message, HumanMessage) else "assistant", str(message.content)
    )


class LangGraphMemoryChat:
    approach = "withLangGraph"

    def __init__(
        self,
        limits: MemoryLimits = MemoryLimits(),  # noqa: B008 - frozen
        *,
        clock: Callable[[], datetime] = utc_now,
        model: BaseChatModel | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str = "",
        default_model: str = "meta-llama/llama-3.1-8b-instruct",
    ) -> None:
        self._limits = limits
        self._model = model  # a stand-in in tests
        self._base_url = base_url
        self._api_key = api_key
        self._default_model = default_model
        self._saver = InMemorySaver()
        self._reader = self._graph(None)  # reads and edits the state; never calls a model
        self._index = ConversationIndex(limits, self._saver.delete_thread, clock)

    def _graph(self, llm: BaseChatModel | None):  # noqa: ANN202 - a compiled graph
        def respond(state: MemoryState) -> MemoryState:
            assert llm is not None
            history = window_messages(
                list(state.get("messages", [])), self._limits.max_messages, self._limits.max_chars
            )
            reply = llm.invoke([SystemMessage(SYSTEM_PROMPT), *history, *state["new"]])
            return {"messages": [*state["new"], reply], "used": len(history)}

        graph = StateGraph(MemoryState)
        graph.add_node("respond", respond)
        graph.add_edge(START, "respond")
        graph.add_edge("respond", END)
        return graph.compile(checkpointer=self._saver)

    def create(self) -> Created:
        return self._index.create()

    def _llm(self, model: str | None) -> tuple[BaseChatModel, str]:
        name = model or self._default_model
        if self._model is not None:
            return self._model, name
        if not self._api_key.strip():
            raise UnavailableError("OPENROUTER_API_KEY is not set. Put it in the environment.")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=name, base_url=self._base_url, api_key=self._api_key, max_retries=0
        ), name

    def chat(self, conversation_id: str, messages: list[Message], model: str | None) -> Answer:
        entry = self._index.use(conversation_id)
        llm, name = self._llm(model)
        config = {"configurable": {"thread_id": conversation_id}}
        new = [
            HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in messages
        ]
        started = time.monotonic()
        try:
            # NO lock is held here: the model is called while other conversations can be read
            result = self._graph(llm).invoke({"new": new}, config)
        except UnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - by kind, never by the service's own text
            raise UnavailableError(f"The model call failed ({type(exc).__name__}).") from exc
        reply = result["messages"][-1]
        with entry.lock:
            if entry.removed:
                # deleted or evicted during the call: the saver may have written the turn after the
                # delete, so the thread is deleted again
                self._saver.delete_thread(conversation_id)
                stored = 0
            else:
                stored_messages = list(self._reader.get_state(config).values["messages"])
                kept = stored_messages[-self._limits.max_stored_messages :]
                # The saver keeps a checkpoint per step and `prune` is not implemented for
                # InMemorySaver (measured), so the thread is rewritten as one checkpoint holding only
                # the kept messages: this bounds the messages and the memory in one go.
                self._saver.delete_thread(conversation_id)
                self._reader.update_state(config, {"messages": kept}, as_node="respond")
                stored = len(kept)
        meta = dict(reply.usage_metadata or {})
        usage = Usage(
            name,
            meta.get("input_tokens"),
            meta.get("output_tokens"),
            int((time.monotonic() - started) * 1000),
        )
        return Answer(str(reply.text), conversation_id, int(result.get("used", 0)), stored, usage)

    def get(self, conversation_id: str) -> Conversation:
        entry = self._index.peek(conversation_id)
        with entry.lock:
            values = self._reader.get_state({"configurable": {"thread_id": conversation_id}}).values
            stored = [to_message(m) for m in values.get("messages", [])]
        return Conversation(conversation_id, stored, self._index.expires_at(entry))

    def delete(self, conversation_id: str) -> None:
        self._index.delete(conversation_id)
