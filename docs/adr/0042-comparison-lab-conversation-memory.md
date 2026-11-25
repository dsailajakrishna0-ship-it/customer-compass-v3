# 0042 — Comparison lab, conversation memory: LangChain message history against the LangGraph checkpointer

- **Status:** Accepted (E5.6; measured with a scripted model and a clock the tests move, no live model run)
- **Date:** 2026-11-27
- **Roadmap sub-stage:** E5.6 (the Python twin of the Java edition's J8.6; the contract is [ADR 0036](0036-conversation-memory.md); plan in [the E5 guide](../stages/E5-comparison-lab.md))

## Context

The server keeps a conversation's history between requests. The contract (ADR 0036): an id, a window of **20 messages and 16,000 characters** sent with each turn, **24 hours after the last use**, **1,000 conversations** (least recently used goes first), **200 stored messages** per conversation, a turn stored **only after it succeeded**, an unknown id is a **404**, and **no lock is held while the model is called**. The question here is how much of that each 🟦framework's memory gives and how much stays ours.

## Decision

1. **The same face as Java's memory backends:** `POST /api/v1/conversations` (201), `POST /api/v1/chat/memory` (`conversationId`, `messages`, optional `model`; the conversation id is required on every turn in the lab), `GET` and `DELETE /api/v1/conversations/{id}` (204), `GET /health`. The answer has `message`, `conversationId`, `memory.messagesUsed` and `memory.messagesStored` (counts only, never content) and `usage`. The limits come from `MEMORY_MAX_MESSAGES`, `MEMORY_MAX_CHARS`, `MEMORY_TTL_HOURS`, `MEMORY_MAX_CONVERSATIONS` and `MEMORY_MAX_STORED_MESSAGES`.
2. **Ours in both (`lab_common/memory.py`, `ConversationIndex`):** random ids, the time limit after the last use (reading does not extend it), the cap with least-recently-used eviction, "this conversation is gone" so that a turn still running when its conversation is deleted does not bring it back, and the face. These are the rules **no library gives**.
3. **withLangChain, port 19162:** `InMemoryChatMessageHistory` keeps the messages, `RunnableWithMessageHistory` loads them in front of the new messages and saves the turn after the model answered, and `trim_messages` makes the window (twice: the last 20 messages, then the most recent that fit 16,000 characters).
4. **withLangGraph, port 19161:** the graph state holds the messages, `InMemorySaver` keeps them per thread id (the conversation id), and the same `trim_messages` makes the window inside the model node. **The new messages travel in their own state key** and join the stored ones only when the model answered.

## What the libraries did without our code (measured in `comparisons/tests/test_memory.py`)

| Point | withLangChain | withLangGraph |
| --- | --- | --- |
| Keeping the messages per conversation | `InMemoryChatMessageHistory` | the checkpointer, keyed by thread id |
| Loading the history in front of the new messages | `RunnableWithMessageHistory` (it loads **everything**: with 30 stored messages and no window the model got all 30 and the new one) | the node reads the state |
| Storing the turn only after the model answered | **yes**: a failing model call stored nothing | **only with our design** (next table) |
| The window by count and by characters | `trim_messages` (`strategy="last"`, a counting function): the most recent that fit; **a single message longer than the limit is dropped whole, leaving no history** | the same |

## What each needed from us

| Rule | withLangChain | withLangGraph |
| --- | --- | --- |
| A failed turn stores nothing | free (above) | the obvious design (the input goes straight into the messages channel) **stores the failed turn's question** (measured); the fix is the separate `new` key |
| The bound of 200 stored messages | cut the history list to the last N under the conversation's lock | **there is no way to prune**: `InMemorySaver` keeps three checkpoints per turn for ever (15 after 5 turns) and its `prune` **raises `NotImplementedError`** (measured). Our fix: after each turn the thread is deleted and rewritten as one checkpoint holding the kept messages (1 checkpoint after 5 turns) |
| Deleting a conversation | drop the history object | `delete_thread`; a turn running during the delete may write after it, so the thread is deleted again |
| Messages of an evicted or expired conversation | dropped through `ConversationIndex` | the same |

## A finding about LangChain itself

**Both classes of the LangChain approach are deprecated.** In a fresh interpreter `InMemoryChatMessageHistory` warns "deprecated in LangChain 1.6.4 and will be removed in 2.0.0" and `RunnableWithMessageHistory` warns "deprecated. Use LangGraph's built-in persistence instead." (measured, quoted from the library's own warnings). So the LangChain way of keeping memory is, by LangChain's own account, the LangGraph way (withLangGraph here, or `create_agent` with a checkpointer). The withLangChain approach is kept because it is what many existing projects and tutorials still use, and because it shows what the older path gave for free (a save-after-success, a one-line history loader) and what it did not (a window, a bound).

## Concurrency (the rule "no lock across the model call")

Both approaches call the model with no lock held (a test starts a turn, makes the model wait, and reads this conversation, another conversation and creates one meanwhile). A turn whose conversation is deleted during the call is still answered and stores nothing (`messagesStored` is 0, the conversation stays gone).

**Size** (non-blank, non-comment lines, docstrings included): withLangChain 119, withLangGraph 128; shared `memory.py` (limits, index, face) 294.

## How this was run

`just comparisons-test` (212 tests with the E5.5 ones, no key, no network, in CI; the memory tests were run 30 times in a row without a failure). Both backends were also started once through `just` with a fake key and an unreachable model address: a conversation is created (201), a turn is a 503 `The model call failed (OpenAIConnectionError).` and **stores nothing** (the conversation reads back with no messages), delete is a 204 and a read after it is a 404, and the fake key is in no log line.

**Not measured:** a real model's answers with real history, the cost of the rewrite per turn on a long conversation (it copies the kept messages each turn), a durable store (both are lost on a restart; the application keeps its history in Postgres), and two concurrent turns on one conversation (not tested; the contract allows them to interleave).
