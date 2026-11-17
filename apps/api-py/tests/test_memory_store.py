"""Conversation memory store (ADR 0036) against the real Postgres: the window, the whole-turn write,
the time limit, the cap and deletion. No model, no network."""

import asyncio
from uuid import uuid4

import pytest

from app.config import reset_settings
from app.db import get_pool
from app.memory import store
from app.memory.store import StoredMessage as M


def msgs(*pairs: tuple[str, str]) -> list[M]:
    return [M(r, c) for r, c in pairs]


# ---- the window (pure)


def test_window_keeps_the_most_recent_messages():
    history = msgs(("user", "a"), ("assistant", "b"), ("user", "c"), ("assistant", "d"))
    assert store.window(history, 2, 1000) == msgs(("user", "c"), ("assistant", "d"))


def test_window_never_starts_with_an_answer():
    history = msgs(("user", "a"), ("assistant", "b"), ("user", "c"), ("assistant", "d"))
    # a count of 3 would start on the assistant "b": it is dropped with its question gone
    assert store.window(history, 3, 1000) == msgs(("user", "c"), ("assistant", "d"))


def test_window_trims_from_the_oldest_by_characters():
    history = msgs(
        ("user", "x" * 10), ("assistant", "y" * 10), ("user", "z" * 10), ("assistant", "w" * 10)
    )
    assert store.window(history, 20, 20) == msgs(("user", "z" * 10), ("assistant", "w" * 10))


def test_window_can_be_empty():
    assert store.window([], 20, 100) == []
    assert store.window(msgs(("user", "a")), 0, 100) == []
    assert store.window(msgs(("user", "x" * 50)), 20, 10) == []


# ---- the real database


async def clean():
    pool = await get_pool()
    await pool.execute("DELETE FROM conversations")


@pytest.mark.asyncio
async def test_a_turn_is_stored_and_read_back_in_order():
    await clean()
    c = await store.create_conversation()
    assert await store.append_turn(c.id, "q1", "a1") == 2
    assert await store.append_turn(c.id, "q2", "a2") == 4
    conversation, messages = await store.get_conversation(c.id)
    assert conversation.id == c.id
    assert [(m.role, m.content) for m in messages] == [
        ("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2"),
    ]  # fmt: skip
    window, stored = await store.load_window(c.id)
    assert stored == 4 and [m.content for m in window] == ["q1", "a1", "q2", "a2"]


@pytest.mark.asyncio
async def test_the_window_follows_the_settings(monkeypatch):
    await clean()
    monkeypatch.setenv("MEMORY_MAX_MESSAGES", "2")
    reset_settings()
    c = await store.create_conversation()
    for i in range(3):
        await store.append_turn(c.id, f"q{i}", f"a{i}")
    window, stored = await store.load_window(c.id)
    assert stored == 6 and [m.content for m in window] == ["q2", "a2"]


@pytest.mark.asyncio
async def test_an_unknown_conversation_is_not_found():
    with pytest.raises(store.ConversationNotFoundError):
        await store.load_window(str(uuid4()))
    with pytest.raises(store.ConversationNotFoundError):
        await store.append_turn(str(uuid4()), "q", "a")
    with pytest.raises(store.ConversationNotFoundError):
        await store.get_conversation(str(uuid4()))
    assert await store.delete_conversation(str(uuid4())) is False


@pytest.mark.asyncio
async def test_an_expired_conversation_is_not_found_and_is_deleted():
    await clean()
    c = await store.create_conversation()
    await store.append_turn(c.id, "q", "a")
    pool = await get_pool()
    await pool.execute(
        "UPDATE conversations SET last_used_at = NOW() - INTERVAL '25 hours' WHERE id = $1::uuid",
        c.id,
    )
    with pytest.raises(store.ConversationNotFoundError):
        await store.load_window(c.id)
    assert await pool.fetchval("SELECT COUNT(*) FROM conversations") == 0
    assert await pool.fetchval("SELECT COUNT(*) FROM conversation_messages") == 0


@pytest.mark.asyncio
async def test_a_stored_turn_extends_the_limit_but_a_read_does_not():
    await clean()
    c = await store.create_conversation()
    pool = await get_pool()
    old = "NOW() - INTERVAL '23 hours'"
    await pool.execute(f"UPDATE conversations SET last_used_at = {old} WHERE id = $1::uuid", c.id)  # noqa: S608
    await store.get_conversation(c.id)
    await store.load_window(c.id)
    after_reads = await pool.fetchval(
        "SELECT NOW() - last_used_at > INTERVAL '22 hours' FROM conversations WHERE id = $1::uuid",
        c.id,
    )
    assert after_reads is True
    await store.append_turn(c.id, "q", "a")
    after_turn = await pool.fetchval(
        "SELECT NOW() - last_used_at < INTERVAL '1 minute' FROM conversations WHERE id = $1::uuid",
        c.id,
    )
    assert after_turn is True


@pytest.mark.asyncio
async def test_creating_removes_the_expired_ones():
    await clean()
    old = await store.create_conversation()
    pool = await get_pool()
    await pool.execute(
        "UPDATE conversations SET last_used_at = NOW() - INTERVAL '48 hours' WHERE id = $1::uuid",
        old.id,
    )
    await store.create_conversation()
    assert await pool.fetchval("SELECT COUNT(*) FROM conversations") == 1


@pytest.mark.asyncio
async def test_the_cap_deletes_the_least_recently_used(monkeypatch):
    await clean()
    monkeypatch.setenv("MEMORY_MAX_CONVERSATIONS", "2")
    reset_settings()
    first = await store.create_conversation()
    second = await store.create_conversation()
    await store.append_turn(first.id, "q", "a")  # first is now more recently used than second
    third = await store.create_conversation()
    pool = await get_pool()
    ids = {str(r["id"]) for r in await pool.fetch("SELECT id FROM conversations")}
    assert ids == {first.id, third.id} and second.id not in ids


@pytest.mark.asyncio
async def test_delete_removes_the_messages_too():
    await clean()
    c = await store.create_conversation()
    await store.append_turn(c.id, "q", "a")
    assert await store.delete_conversation(c.id) is True
    pool = await get_pool()
    assert await pool.fetchval("SELECT COUNT(*) FROM conversation_messages") == 0
    assert await store.delete_conversation(c.id) is False


@pytest.mark.asyncio
async def test_concurrent_turns_keep_each_pair_together():
    await clean()
    c = await store.create_conversation()
    await asyncio.gather(*(store.append_turn(c.id, f"q{i}", f"a{i}") for i in range(8)))
    _, messages = await store.get_conversation(c.id)
    assert len(messages) == 16
    for i in range(0, 16, 2):
        assert messages[i].role == "user" and messages[i + 1].role == "assistant"
        assert messages[i].content[1:] == messages[i + 1].content[1:]


@pytest.mark.asyncio
async def test_stored_messages_are_bounded_to_the_newest():
    await clean()
    c = await store.create_conversation()
    for i in range(120):
        await store.append_turn(c.id, f"q{i}", f"a{i}")
    _, messages = await store.get_conversation(c.id)
    assert len(messages) == 200
    assert messages[0].content == "q20" and messages[-1].content == "a119"
    window, stored = await store.load_window(c.id)
    assert stored == 200 and len(window) == 20  # the window is unchanged by the bound


@pytest.mark.asyncio
async def test_a_conversation_below_the_bound_is_untouched():
    await clean()
    c = await store.create_conversation()
    for i in range(5):
        await store.append_turn(c.id, f"q{i}", f"a{i}")
    _, messages = await store.get_conversation(c.id)
    assert len(messages) == 10 and messages[0].content == "q0"


@pytest.mark.asyncio
async def test_a_failed_append_leaves_the_old_messages_intact(monkeypatch):
    await clean()
    monkeypatch.setenv("MEMORY_MAX_STORED_MESSAGES", "4")
    reset_settings()
    c = await store.create_conversation()
    await store.append_turn(c.id, "q0", "a0")
    await store.append_turn(c.id, "q1", "a1")
    pool = await get_pool()
    # an assistant text the database refuses (a NUL character) makes the insert fail after the lock
    with pytest.raises(Exception):  # noqa: B017, PT011 - any database error
        await store.append_turn(c.id, "q2", "bad\x00text")
    _, messages = await store.get_conversation(c.id)
    assert [m.content for m in messages] == ["q0", "a0", "q1", "a1"]
    assert await pool.fetchval("SELECT COUNT(*) FROM conversation_messages") == 4
