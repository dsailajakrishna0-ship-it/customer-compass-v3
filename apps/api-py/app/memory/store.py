"""Conversation memory in Postgres (E4.1, ADR 0036).

A conversation is an unguessable id and its messages. The id is the only access control (the application
has no accounts), so anyone who knows it can read and extend that conversation: stated in the API reference.

The rules this module keeps, each tested:

- a **window**, not the whole history: the most recent `memory_max_messages` stored messages, then trimmed
  from the oldest until they fit in `memory_max_chars` characters, and a window never starts with an
  answer (it starts with the person's message the answer belonged to);
- a **turn is stored whole**: the person's message and the answer are inserted in one transaction, under a
  short advisory lock so another turn on the same conversation cannot slip a message between them (the lock
  is never held while a model runs);
- **time limit and cap**: a conversation expires `memory_ttl_hours` after its last stored turn; an expired
  one is deleted when it is touched, and creating a conversation removes the expired ones; beyond
  `memory_max_conversations` the least recently used is deleted, so storage cannot grow without bound;
- **no content in logs**: nothing here logs a message.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import asyncpg

from app.config import get_settings
from app.db import get_pool


class ConversationNotFoundError(Exception):
    """No such conversation, or it has expired (the two are not told apart)."""


@dataclass(frozen=True)
class StoredMessage:
    role: str
    content: str


@dataclass(frozen=True)
class Conversation:
    id: str
    created_at: datetime
    last_used_at: datetime

    @property
    def expires_at(self) -> datetime:
        return self.last_used_at + timedelta(hours=get_settings().memory_ttl_hours)


def _conversation(row: asyncpg.Record) -> Conversation:
    return Conversation(str(row["id"]), row["created_at"], row["last_used_at"])


def _ttl() -> timedelta:
    return timedelta(hours=get_settings().memory_ttl_hours)


async def delete_expired(conn: asyncpg.Connection) -> int:
    """Removes every conversation whose time limit has passed; the messages go with them."""
    result = await conn.execute(
        "DELETE FROM conversations WHERE last_used_at < NOW() - $1::interval", _ttl()
    )
    return int(result.split()[-1])


async def create_conversation() -> Conversation:
    """Makes a conversation. First the expired ones are removed, then, if the cap is reached, the least
    recently used are deleted to make room."""
    settings = get_settings()
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await delete_expired(conn)
        count = await conn.fetchval("SELECT COUNT(*) FROM conversations")
        excess = count - settings.memory_max_conversations + 1
        if excess > 0:
            await conn.execute(
                "DELETE FROM conversations WHERE id IN "
                "(SELECT id FROM conversations ORDER BY last_used_at ASC, created_at ASC LIMIT $1)",
                excess,
            )
        row = await conn.fetchrow(
            "INSERT INTO conversations (id) VALUES ($1) RETURNING id, created_at, last_used_at",
            uuid4(),
        )
    assert row is not None
    return _conversation(row)


async def _live_conversation(conn: asyncpg.Connection, conversation_id: str) -> Conversation:
    """The conversation, or ConversationNotFoundError. An expired one is deleted on the way."""
    row = await conn.fetchrow(
        "SELECT id, created_at, last_used_at FROM conversations WHERE id = $1",
        UUID(conversation_id),
    )
    if row is None:
        raise ConversationNotFoundError
    conversation = _conversation(row)
    if conversation.expires_at <= datetime.now(tz=conversation.last_used_at.tzinfo):
        await conn.execute("DELETE FROM conversations WHERE id = $1", UUID(conversation_id))
        raise ConversationNotFoundError
    return conversation


def window(messages: list[StoredMessage], max_messages: int, max_chars: int) -> list[StoredMessage]:
    """The part of a history that is sent to the model: the last `max_messages`, trimmed from the oldest
    until the total length is at most `max_chars`, and never starting with an answer."""
    kept = messages[-max_messages:] if max_messages > 0 else []
    total = sum(len(m.content) for m in kept)
    while kept and total > max_chars:
        total -= len(kept[0].content)
        kept = kept[1:]
    while kept and kept[0].role != "user":
        kept = kept[1:]
    return kept


async def load_window(conversation_id: str) -> tuple[list[StoredMessage], int]:
    """(the window to send, how many messages are stored). Raises ConversationNotFoundError for an unknown
    or expired id. Does not extend the time limit: only a stored turn does."""
    settings = get_settings()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _live_conversation(conn, conversation_id)
        rows = await conn.fetch(
            "SELECT role, content FROM conversation_messages WHERE conversation_id = $1 "
            "ORDER BY id DESC LIMIT $2",
            UUID(conversation_id),
            max(settings.memory_max_messages, 0)
            + 1,  # one more than the window, to trim on the right end
        )
        stored = await conn.fetchval(
            "SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = $1",
            UUID(conversation_id),
        )
    recent = [StoredMessage(r["role"], r["content"]) for r in reversed(rows)]
    return window(recent, settings.memory_max_messages, settings.memory_max_chars), int(stored)


async def append_turn(conversation_id: str, user_text: str, assistant_text: str) -> int:
    """Stores a turn: the person's message and the answer, in one transaction, and extends the time limit.
    Returns how many messages the conversation holds now. Raises ConversationNotFoundError if it was
    deleted or expired while the model was answering."""
    pool = await get_pool()
    uid = UUID(conversation_id)
    async with pool.acquire() as conn, conn.transaction():
        # a short lock, held only for the two inserts, keeps another turn's messages out from between ours
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", conversation_id)
        try:
            await _live_conversation(conn, conversation_id)
            await conn.execute(
                "INSERT INTO conversation_messages (conversation_id, role, content) "
                "VALUES ($1, 'user', $2), ($1, 'assistant', $3)",
                uid,
                user_text,
                assistant_text,
            )
        except asyncpg.ForeignKeyViolationError as error:
            raise ConversationNotFoundError from error
        await conn.execute("UPDATE conversations SET last_used_at = NOW() WHERE id = $1", uid)
        stored = await conn.fetchval(
            "SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = $1", uid
        )
    return int(stored)


async def get_conversation(conversation_id: str) -> tuple[Conversation, list[StoredMessage]]:
    """The conversation and every stored message in order (not only the window). Does not extend the
    time limit: reading must not keep a person's content alive."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        conversation = await _live_conversation(conn, conversation_id)
        rows = await conn.fetch(
            "SELECT role, content FROM conversation_messages WHERE conversation_id = $1 ORDER BY id",
            UUID(conversation_id),
        )
    return conversation, [StoredMessage(r["role"], r["content"]) for r in rows]


async def delete_conversation(conversation_id: str) -> bool:
    """Deletes the conversation and its messages now. True if it existed (expired or not)."""
    pool = await get_pool()
    result = await pool.execute("DELETE FROM conversations WHERE id = $1", UUID(conversation_id))
    return result.endswith("1")
