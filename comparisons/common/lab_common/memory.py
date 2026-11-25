"""What every conversation-memory approach implements, the rules of the contract that no library
gives (ids, the time limit, the cap), and the HTTP face they share.

An approach creates a conversation, answers a turn with the stored history in front of the new
messages, reads a conversation back and deletes it. The face is `POST /api/v1/conversations`
(create, 201), `POST /api/v1/chat/memory` with `{"conversationId", "messages", "model"}`,
`GET` and `DELETE /api/v1/conversations/{id}` and `GET /health`. The lab, unlike the application's
chat routes, requires the conversation id on every turn. The rules are ADR 0036 (the contract).
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .chat import Message, UnavailableError, Usage

MAX_MESSAGES = 12
MAX_CONTENT = 4_000
MAX_MODEL = 100
ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
SYSTEM_PROMPT = (
    "You are Compass, a CRM copilot. Answer the user's latest message briefly, using the "
    "conversation so far."
)


@dataclass(frozen=True)
class MemoryLimits:
    """The limits of conversation memory (ADR 0036). Every approach takes one, so the tests can use
    small numbers and the approaches are compared under the same rules."""

    max_messages: int = 20  # how many of the most recent stored messages are sent with a new turn
    max_chars: int = 16_000  # the most characters of history sent; the oldest are left out first
    ttl: timedelta = timedelta(hours=24)  # how long a conversation lives after its last use
    max_conversations: int = 1_000  # creating one more removes the least recently used
    max_stored_messages: int = 200  # how many messages ONE conversation keeps; the oldest go first

    def __post_init__(self) -> None:
        if (
            min(self.max_messages, self.max_chars, self.max_conversations) < 1
            or self.max_stored_messages < 2
        ):
            raise ValueError("Every memory limit must be positive.")
        if self.ttl <= timedelta(0):
            raise ValueError("Every memory limit must be positive.")

    @staticmethod
    def from_environment(env: Mapping[str, str] | None = None) -> MemoryLimits:
        """The defaults, overridden by MEMORY_MAX_MESSAGES, MEMORY_MAX_CHARS, MEMORY_TTL_HOURS,
        MEMORY_MAX_CONVERSATIONS and MEMORY_MAX_STORED_MESSAGES."""
        env = os.environ if env is None else env

        def number(name: str, fallback: int) -> int:
            value = (env.get(name) or "").strip()
            return int(value) if value else fallback

        defaults = MemoryLimits()
        return MemoryLimits(
            number("MEMORY_MAX_MESSAGES", defaults.max_messages),
            number("MEMORY_MAX_CHARS", defaults.max_chars),
            timedelta(hours=number("MEMORY_TTL_HOURS", 24)),
            number("MEMORY_MAX_CONVERSATIONS", defaults.max_conversations),
            number("MEMORY_MAX_STORED_MESSAGES", defaults.max_stored_messages),
        )


@dataclass(frozen=True)
class Created:
    conversation_id: str
    expires_at: datetime


@dataclass(frozen=True)
class Answer:
    """`messages_used` is how many stored messages were sent to the model (the window),
    `messages_stored` how many are stored after this turn. Counts only: never content."""

    message: str
    conversation_id: str
    messages_used: int
    messages_stored: int
    usage: Usage | None = None


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    messages: list[Message]
    expires_at: datetime


class ConversationNotFoundError(RuntimeError):
    """Never created, deleted, evicted, or past its time limit."""

    def __init__(self) -> None:
        super().__init__("Conversation not found or expired.")


class MemoryChat(Protocol):
    approach: str

    def create(self) -> Created: ...

    def chat(self, conversation_id: str, messages: list[Message], model: str | None) -> Answer:
        """`messages` are the NEW messages (the last one is from the user); the stored history goes
        in front of them for the model. Only a successful turn is stored."""
        ...

    def get(self, conversation_id: str) -> Conversation:
        """The stored messages, oldest first. Reading does not extend the conversation's life."""
        ...

    def delete(self, conversation_id: str) -> None: ...


@dataclass
class Entry:
    """One conversation as the index knows it: when it was last used and whether it is gone. A turn
    that is still running when the conversation is deleted checks `removed` before it stores."""

    id: str
    last_used: datetime
    removed: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationIndex:
    """The rules no library gives: random ids, the time limit after the last use, the cap with
    least-recently-used eviction, and "this conversation is gone". Where the messages live is the
    approach's business; `on_remove` is told which id was dropped so it can drop the messages."""

    def __init__(
        self,
        limits: MemoryLimits,
        on_remove: Callable[[str], None],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._limits = limits
        self._on_remove = on_remove
        self._clock = clock
        self._entries: OrderedDict[str, Entry] = OrderedDict()  # least recently used first
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._entries)

    def _expired(self, entry: Entry, now: datetime) -> bool:
        return now >= entry.last_used + self._limits.ttl

    def _drop(self, entry: Entry) -> None:
        entry.removed = True
        self._entries.pop(entry.id, None)
        self._on_remove(entry.id)

    def create(self) -> Created:
        now = self._clock()
        with self._lock:
            for entry in [e for e in self._entries.values() if self._expired(e, now)]:
                self._drop(entry)
            while len(self._entries) >= self._limits.max_conversations:
                self._drop(next(iter(self._entries.values())))
            entry = Entry(str(uuid.uuid4()), now)
            self._entries[entry.id] = entry
            return Created(entry.id, now + self._limits.ttl)

    def _find(self, conversation_id: str, now: datetime) -> Entry:
        entry = self._entries.get(conversation_id)
        if entry is None:
            raise ConversationNotFoundError
        if self._expired(entry, now):
            self._drop(entry)
            raise ConversationNotFoundError
        return entry

    def use(self, conversation_id: str) -> Entry:
        """Finds a live conversation and marks it used (this extends its life), or raises."""
        now = self._clock()
        with self._lock:
            entry = self._find(conversation_id, now)
            entry.last_used = now
            self._entries.move_to_end(entry.id)
            return entry

    def peek(self, conversation_id: str) -> Entry:
        """Finds a live conversation WITHOUT extending its life (reading does not)."""
        with self._lock:
            return self._find(conversation_id, self._clock())

    def expires_at(self, entry: Entry) -> datetime:
        return entry.last_used + self._limits.ttl

    def delete(self, conversation_id: str) -> None:
        with self._lock:
            self._drop(self._find(conversation_id, self._clock()))


def _validate(body: object) -> tuple[str, list[Message], str | None]:
    if not isinstance(body, dict):
        raise ValueError("The body must be a JSON object.")
    conversation_id = body.get("conversationId")
    if not isinstance(conversation_id, str) or not ID.fullmatch(conversation_id):
        raise ValueError("conversationId is required and must be a conversation id.")
    items = body.get("messages")
    if not isinstance(items, list):
        raise ValueError("messages is required and must be a list.")
    if not 1 <= len(items) <= MAX_MESSAGES:
        raise ValueError(f"messages must hold 1 to {MAX_MESSAGES} items.")
    messages: list[Message] = []
    for item in items:
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        if role not in ("user", "assistant"):
            raise ValueError("A message role must be user or assistant.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("A message content must be a non-blank string.")
        if len(content) > MAX_CONTENT:
            raise ValueError(f"A message content is limited to {MAX_CONTENT} characters.")
        messages.append(Message(role, content))
    if messages[-1].role != "user":
        raise ValueError("The last message must be from the user.")
    model = body.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("model must be a string.")
    return conversation_id, messages, (model if model and model.strip() else None)


def create_memory_app(memory: MemoryChat) -> FastAPI:
    app = FastAPI(title=f"Memory backend: {memory.approach}", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    not_found = JSONResponse({"detail": "Conversation not found or expired."}, status_code=404)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "approach": memory.approach}

    @app.post("/api/v1/conversations")
    async def create() -> JSONResponse:
        try:
            created = await run_in_threadpool(memory.create)
        except Exception:  # noqa: BLE001
            message = "The conversation could not be created."
            return JSONResponse({"error": message, "detail": message}, status_code=503)
        return JSONResponse(
            {
                "conversationId": created.conversation_id,
                "expiresAt": created.expires_at.isoformat(),
            },
            status_code=201,
        )

    @app.get("/api/v1/conversations/{conversation_id}")
    async def read(conversation_id: str) -> JSONResponse:
        if not ID.fullmatch(conversation_id):
            return not_found  # an id that cannot be one of ours is simply not a conversation
        try:
            conversation = await run_in_threadpool(memory.get, conversation_id)
        except ConversationNotFoundError:
            return not_found
        except Exception:  # noqa: BLE001
            message = "The conversation could not be read."
            return JSONResponse({"error": message, "detail": message}, status_code=503)
        return JSONResponse(
            {
                "conversationId": conversation.conversation_id,
                "messages": [{"role": m.role, "content": m.content} for m in conversation.messages],
                "expiresAt": conversation.expires_at.isoformat(),
            }
        )

    @app.delete("/api/v1/conversations/{conversation_id}")
    async def remove(conversation_id: str) -> Response:
        if not ID.fullmatch(conversation_id):
            return not_found
        try:
            await run_in_threadpool(memory.delete, conversation_id)
        except ConversationNotFoundError:
            return not_found
        except Exception:  # noqa: BLE001
            message = "The conversation could not be read."
            return JSONResponse({"error": message, "detail": message}, status_code=503)
        return Response(status_code=204)

    @app.post("/api/v1/chat/memory")
    async def chat(request: Request) -> JSONResponse:
        import json

        try:
            conversation_id, messages, model = _validate(
                json.loads((await request.body()).decode("utf-8") or "null")
            )
        except (ValueError, UnicodeDecodeError) as exc:
            known = (
                "The body must",
                "conversationId ",
                "messages ",
                "A message",
                "The last",
                "model ",
            )
            detail = str(exc) if str(exc).startswith(known) else "The body is not valid JSON."
            return JSONResponse({"detail": detail}, status_code=422)
        try:
            answer = await run_in_threadpool(memory.chat, conversation_id, messages, model)
        except ConversationNotFoundError:
            return not_found
        except UnavailableError as exc:
            return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=503)
        except Exception:  # noqa: BLE001 - never the exception's own text: it can carry a URL
            message = "The conversation could not be answered."
            return JSONResponse({"error": message, "detail": message}, status_code=503)
        out: dict = {
            "approach": memory.approach,
            "message": answer.message,
            "conversationId": answer.conversation_id,
            "memory": {
                "messagesUsed": answer.messages_used,
                "messagesStored": answer.messages_stored,
            },
        }
        if answer.usage is not None:
            out["usage"] = {
                "model": answer.usage.model,
                "tokensIn": answer.usage.tokens_in,
                "tokensOut": answer.usage.tokens_out,
                "latencyMs": answer.usage.latency_ms,
            }
        return JSONResponse(out)

    return app
