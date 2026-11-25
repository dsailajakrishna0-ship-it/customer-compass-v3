"""Conversation memory with LangChain: `InMemoryChatMessageHistory` keeps the messages,
`RunnableWithMessageHistory` loads them in front of the new messages and saves the turn after the
model answered, and `trim_messages` makes the window. What we add: the ids, the time limit and the
cap (`ConversationIndex`), the bound on stored messages, and "deleted during the call stays
deleted". Decisions and measurements: docs/adr/0042.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

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
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM_PROMPT), MessagesPlaceholder("history"), MessagesPlaceholder("input")]
)


def to_message(message: AnyMessage) -> Message:
    return Message(
        "user" if isinstance(message, HumanMessage) else "assistant", str(message.content)
    )


class LangChainMemoryChat:
    approach = "withLangChain"

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
        self._histories: dict[str, InMemoryChatMessageHistory] = {}
        self._index = ConversationIndex(limits, lambda cid: self._histories.pop(cid, None), clock)

    def create(self) -> Created:
        created = self._index.create()
        self._histories[created.conversation_id] = InMemoryChatMessageHistory()
        return created

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
        entry = self._index.use(conversation_id)  # raises when unknown or expired; extends the life
        history = self._histories[conversation_id]
        llm, name = self._llm(model)
        used: list[int] = []

        def trim(inputs: dict) -> dict:
            window = window_messages(
                inputs["history"], self._limits.max_messages, self._limits.max_chars
            )
            used.append(len(window))
            return {**inputs, "history": window}

        chain = RunnableWithMessageHistory(
            RunnableLambda(trim) | PROMPT | llm,
            lambda _session: history,
            input_messages_key="input",
            history_messages_key="history",
        )
        new = [
            HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in messages
        ]
        started = time.monotonic()
        try:
            # NO lock is held here: the model is called while other conversations (and this one) can be read
            reply = chain.invoke(
                {"input": new}, config={"configurable": {"session_id": conversation_id}}
            )
        except UnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - by kind, never by the service's own text
            raise UnavailableError(f"The model call failed ({type(exc).__name__}).") from exc
        usage_meta = dict(reply.usage_metadata or {})
        with entry.lock:
            if entry.removed:
                stored = 0  # deleted or evicted during the call: it stays deleted, the answer is still returned
            else:
                excess = len(history.messages) - self._limits.max_stored_messages
                if excess > 0:
                    history.messages = history.messages[excess:]
                stored = len(history.messages)
        usage = Usage(
            name,
            usage_meta.get("input_tokens"),
            usage_meta.get("output_tokens"),
            int((time.monotonic() - started) * 1000),
        )
        return Answer(str(reply.text), conversation_id, used[0] if used else 0, stored, usage)

    def get(self, conversation_id: str) -> Conversation:
        entry = self._index.peek(conversation_id)
        with entry.lock:
            stored = [to_message(m) for m in self._histories[conversation_id].messages]
        return Conversation(conversation_id, stored, self._index.expires_at(entry))

    def delete(self, conversation_id: str) -> None:
        self._index.delete(conversation_id)
