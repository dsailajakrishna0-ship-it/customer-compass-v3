"""Conversation memory endpoints (E4.1, ADR 0036): make, read and delete a conversation.

The id is the only access control (the application has no accounts): anyone who knows it can read,
extend and delete that conversation. It is an unguessable UUID, never listed by any endpoint.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from app.memory import store
from app.memory.turn import NOT_FOUND

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _uuid(conversation_id: str) -> str:
    try:
        return str(UUID(conversation_id))
    except ValueError as error:
        # a malformed id is the same 404 as an unknown one: nothing to tell apart
        raise HTTPException(status_code=404, detail=NOT_FOUND) from error


def _json(conversation: store.Conversation) -> dict:
    return {
        "conversationId": conversation.id,
        "createdAt": conversation.created_at.isoformat(),
        "lastUsedAt": conversation.last_used_at.isoformat(),
        "expiresAt": conversation.expires_at.isoformat(),
    }


@router.post("", status_code=201)
async def create_conversation():
    """Makes an empty conversation and returns its id. Expired conversations are removed, and beyond
    the cap the least recently used is deleted."""
    return _json(await store.create_conversation())


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str):
    """The conversation and all of its stored messages. Reading does not extend its time limit."""
    try:
        conversation, messages = await store.get_conversation(_uuid(conversation_id))
    except store.ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from error
    return {
        **_json(conversation),
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str) -> Response:
    """Deletes the conversation and its messages now. 404 if there is none."""
    if not await store.delete_conversation(_uuid(conversation_id)):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return Response(status_code=204)
