"""One chat turn with memory (E4.1, ADR 0036): the helper the chat routes share.

A route calls `begin(body)` before it does anything else (an unknown or expired conversation is a 404
before any model runs or any quota is spent), puts `turn.history` before the request's own messages, and
calls `turn.finish(response, user_text)` after the answer is ready. Without a conversationId `begin`
returns an inactive turn whose history is empty and whose `finish` returns the response unchanged, so a
request that does not use memory behaves exactly as before.
"""

import logging
from dataclasses import dataclass, field

from fastapi import HTTPException

from app.llm.types import ChatMessage
from app.memory import store

logger = logging.getLogger("app.memory")

NOT_FOUND = "Conversation not found or expired."


@dataclass
class Turn:
    conversation_id: str | None = None
    history: list[ChatMessage] = field(default_factory=list)
    stored: int = 0

    @property
    def active(self) -> bool:
        return self.conversation_id is not None

    def with_history(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """The stored window first, then the request's own messages."""
        return [*self.history, *messages]

    async def finish(self, response: dict, user_text: str) -> dict:
        """Stores the person's message (the guard-neutralized text) and the answer, and adds
        `conversationId` and the `memory` counts to the response. A no-op when memory is not used.
        A conversation deleted or expired while the model was answering is a 404."""
        if self.conversation_id is None:
            return response
        try:
            now_stored = await store.append_turn(
                self.conversation_id, user_text, response["message"]
            )
        except store.ConversationNotFoundError as error:
            raise HTTPException(status_code=404, detail=NOT_FOUND) from error
        # counts only: a message is never logged (ADR 0036)
        logger.info("memory_turn used=%d stored=%d", len(self.history), now_stored)
        return {
            **response,
            "conversationId": self.conversation_id,
            "memory": {"messagesUsed": len(self.history), "messagesStored": now_stored},
        }


async def begin(conversation_id: str | None) -> Turn:
    """Loads the window for a conversation, or an inactive turn when there is no id. 404 if the
    conversation does not exist or has expired."""
    if conversation_id is None:
        return Turn()
    try:
        window, stored = await store.load_window(conversation_id)
    except store.ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from error
    history: list[ChatMessage] = [{"role": m.role, "content": m.content} for m in window]  # type: ignore[typeddict-item]
    return Turn(conversation_id, history, stored)
