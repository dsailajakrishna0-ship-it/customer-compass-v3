# 0036 — Conversation memory: the server keeps the history

- **Status:** Accepted (implemented in E4.1; the amendments from the implementation are listed at the end)
- **Date:** 2026-11-18
- **Roadmap sub-stage:** E4.1 (the Python edition goes first; the Java lab comparison J8.6 follows the same contract)

## Context

Today every chat endpoint is **stateless**: the client resends the whole conversation (1 to 12 messages) on every request, and the server forgets it. That keeps the server simple, but a conversation cannot continue from another device, the 12-message cap is a hard ceiling, and every client must carry the history itself. **Memory** means the server keeps the conversation between requests. It also brings new obligations: the history is **customer content**, so its size, its lifetime and who may read it have to be decided, not left to chance.

## Decision

1. **An optional `conversationId` on every chat request** (`POST /api/v1/chat`, `/chat/rag`, `/chat/crm`, `/chat/tools`, `/chat/multi`). Without it the endpoint behaves **exactly as today** (stateless), so the change is additive and no existing client breaks. In JSON the field is camelCase, like `mcpServer`.
2. **`POST /api/v1/conversations`** creates a conversation and answers `201 {"conversationId": "<random UUID v4>", "expiresAt": "<ISO time>"}`. The id is a random, unguessable UUID: **it is the only access control, because the application has no user accounts**, and this is stated in the API reference. Anyone who knows an id can read and extend that conversation.
3. **With a `conversationId`, `messages` are the NEW messages of the turn** (normally exactly one user message; the last one must be from the user, as today). The server loads the stored history, puts it **before** the new messages and calls the model as today. Guards, retrieval and tools are unchanged: the question for retrieval is still the last user message.
4. **A window, not the whole history.** The history used is the most recent `MEMORY_MAX_MESSAGES` stored messages (default **20**), then trimmed from the oldest end until the total length is at most `MEMORY_MAX_CHARS` characters (default **16,000**). Characters are the budget, not tokens (a token-accurate budget is out of scope). Older messages are not sent, but they stay stored, up to the bound in decision 4a.
4a. **Stored messages are bounded per conversation:** `MEMORY_MAX_STORED_MESSAGES`, default **200**; the oldest are deleted when a turn is appended, in the same transaction as the insert, so a conversation always holds its newest messages and one client cannot grow it without limit (every turn extends the 24-hour clock, so the time limit alone does not bound it). The window logic is unchanged.
5. **A turn is stored only after it succeeds, and in one transaction**: the new user message and the assistant's answer are appended together, so a failed turn stores nothing and a pair never splits. What is stored for the user message is the **guard-neutralized text** the model saw (never the raw injection attempt).
6. **The answer is unchanged, plus** `"conversationId"` (echoed) and `"memory": {"messagesUsed": <n>, "messagesStored": <m>}`: counts only, never content. Without a `conversationId` neither field appears.
7. **An unknown or expired id is `404`** with `{"detail": "Conversation not found or expired."}`. The server never silently starts a new conversation under an id the client supplied.
8. **`GET /api/v1/conversations/{id}`** answers `{"conversationId", "messages": [{"role", "content"}], "expiresAt"}`; **`DELETE /api/v1/conversations/{id}`** answers `204` and removes the conversation and its messages at once. Deleting is how a person's content is removed before the time limit.
9. **Retention.** A conversation expires `MEMORY_TTL_HOURS` (default **24**) after its **last use**; using it extends the time. An expired conversation is deleted when it is touched, and creating a conversation removes the expired ones. A global cap `MEMORY_MAX_CONVERSATIONS` (default **1,000**): creating a conversation beyond it deletes the **least recently used** one. So storage cannot grow without bound.
10. **Content is never logged or traced.** The tracing spans record counts (`memory.messages_used`, `memory.messages_stored`) and never a message; the audit and log lines never contain history.
11. **Concurrency.** Two turns on one conversation at the same moment each read the history as it was when they started and each append their own pair in one transaction; messages are ordered by commit. Nothing is corrupted, but the second turn may not have seen the first. This is documented, not locked, because holding a lock across a model call would stall the conversation.
12. **Storage: Postgres**, two tables (`conversations`: id, created_at, last_used_at; `conversation_messages`: id, conversation_id with cascade delete, role, content, created_at), Alembic migration `0004`. Postgres is already the system of record for CRM and ingestion data and survives a restart.
13. **Limits stay:** a message's content is at most 4,000 characters, and a request still carries at most 12 messages (with memory, normally one).
14. **Out of scope:** user accounts and authorisation, summaries or long-term facts about a customer, token-accurate budgets, streaming, the agent routes (`/agent`, `/supervise`), and the web app (a separate PR).

## The lab contract (the Java comparison, J8.6)

The Java lab backends implement the same shape on their own ports with **plain chat only** (no tools, no retrieval), so the three approaches (hand-written, Spring AI's `ChatMemory`, LangChain4j's `ChatMemory`) can be compared on the same rules: `POST /api/v1/conversations`; `POST /api/v1/chat/memory` with `{"conversationId": "...", "messages": [...], "model": "optional"}`; `GET` and `DELETE /api/v1/conversations/{id}`; the same window, character budget, time limit, cap and stored-messages bound as above (defaults: 20 messages, 16,000 characters, 24 hours, 1,000 conversations, 200 stored messages per conversation).

## Consequences

- The change is additive and opt-in; a client that never sends a `conversationId` is unaffected.
- **The server now holds customer content.** The decisions above (window, time limit, cap, deletion, no logging, neutralized storage) are what make that acceptable; the unguessable id is the only access control until the application has accounts. A deployment that exposes the API beyond one trusted user must add authentication before turning memory on for real data.
- Stored history is replayed to the model on later turns. User messages were guarded when stored; assistant messages are the model's own earlier answers. Both are conversation history, not instructions the server trusts beyond that.
- Not measured: how much the longer prompts cost in tokens, and whether a model's answers improve with history.

## Amendments from the implementation (E4.1)

- **Decision 9 refined.** Only a **stored turn** extends the time limit. A `GET` of the conversation, and loading the window for a turn that then fails, do **not**: reading must not keep a person's content alive, and a failed turn changes nothing. A conversation touched after its limit is deleted on the spot (404).
- **Decision 11 changed: a short advisory lock.** The two inserts of a turn run under `pg_advisory_xact_lock` on the conversation id, so two simultaneous turns cannot interleave a user message between another turn's pair. The lock is held only for the inserts and **never across a model call**; the conclusion of the original text still holds: a second turn may not have seen the first.
- **Decisions 2 and 8: the response shape.** `POST /conversations` answers `201 {"conversationId", "createdAt", "lastUsedAt", "expiresAt"}`; `GET /conversations/{id}` answers the same plus `messages`. A **malformed id is the same 404** as an unknown one on these two endpoints; on the chat endpoints a malformed `conversationId` is a `422` (request validation), as is a last message that is not from the user.
- **Decision 7.** The 404 is raised **before** the guard, retrieval or any model runs, so an unknown id spends no quota. A conversation deleted or expired **while** the model answers is a 404 at the storing step, and the answer is not returned.
- **Decision 5.** Stored for the user is the text the guard returned (`neutralized_text`), also on the "nothing found" answers. In `/chat/multi` it is the neutralized text from the graph's guard node.
- **Decision 10.** One span, `memory.append_turn`, with `memory.messages_used` and `memory.messages_stored`. The log line is `memory_turn used=<n> stored=<m>`.
- **Window rule added.** A window never starts with an answer: if cutting by count or characters would leave an assistant message first, it is dropped, so the model always sees a question before its answer.
- **Not done here:** the web app (a separate PR) and the agent routes (decision 14).
