from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from lab_common.chat import Message, UnavailableError, Usage
from lab_common.memory import (
    Answer,
    Conversation,
    ConversationNotFoundError,
    Created,
    create_memory_app,
)

CID = "0b8f7c2e-6a51-4c0e-9d57-7f1f0b3c1a11"
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


class FakeMemory:
    approach = "fake"

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def create(self):
        return Created(CID, NOW)

    def chat(self, conversation_id, messages, model):
        self.calls.append((conversation_id, messages, model))
        if self.error:
            raise self.error
        return Answer("hello", conversation_id, 2, 4, Usage("m", 3, 4, 12))

    def get(self, conversation_id):
        if self.error:
            raise self.error
        return Conversation(
            conversation_id, [Message("user", "hi"), Message("assistant", "hello")], NOW
        )

    def delete(self, conversation_id):
        if self.error:
            raise self.error


def client(memory):
    return TestClient(create_memory_app(memory))


def test_health_names_the_approach():
    assert client(FakeMemory()).get("/health").json() == {"status": "ok", "approach": "fake"}


def test_create_is_201_with_the_id_and_the_expiry():
    response = client(FakeMemory()).post("/api/v1/conversations")
    assert response.status_code == 201
    assert response.json() == {"conversationId": CID, "expiresAt": NOW.isoformat()}


def test_a_turn_answers_with_the_memory_counts_and_the_usage():
    memory = FakeMemory()
    response = client(memory).post(
        "/api/v1/chat/memory",
        json={"conversationId": CID, "messages": [{"role": "user", "content": "hi"}], "model": " "},
    )
    assert response.status_code == 200
    assert response.json() == {
        "approach": "fake",
        "message": "hello",
        "conversationId": CID,
        "memory": {"messagesUsed": 2, "messagesStored": 4},
        "usage": {"model": "m", "tokensIn": 3, "tokensOut": 4, "latencyMs": 12},
    }
    assert memory.calls == [(CID, [Message("user", "hi")], None)]


def test_read_and_delete():
    api = client(FakeMemory())
    body = api.get(f"/api/v1/conversations/{CID}").json()
    assert body["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert api.delete(f"/api/v1/conversations/{CID}").status_code == 204


def test_an_id_that_cannot_be_ours_is_a_404_and_so_is_an_unknown_one():
    api = client(FakeMemory(ConversationNotFoundError()))
    assert api.get("/api/v1/conversations/not-an-id").status_code == 404
    assert api.get(f"/api/v1/conversations/{CID}").json() == {
        "detail": "Conversation not found or expired."
    }
    assert api.delete(f"/api/v1/conversations/{CID}").status_code == 404
    turn = api.post(
        "/api/v1/chat/memory",
        json={"conversationId": CID, "messages": [{"role": "user", "content": "x"}]},
    )
    assert turn.status_code == 404


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ([], "The body must be a JSON object."),
        ({"messages": []}, "conversationId is required and must be a conversation id."),
        (
            {"conversationId": "x", "messages": []},
            "conversationId is required and must be a conversation id.",
        ),
        ({"conversationId": CID}, "messages is required and must be a list."),
        ({"conversationId": CID, "messages": []}, "messages must hold 1 to 12 items."),
        (
            {"conversationId": CID, "messages": [{"role": "system", "content": "x"}]},
            "A message role must be user or assistant.",
        ),
        (
            {"conversationId": CID, "messages": [{"role": "user", "content": " "}]},
            "A message content must be a non-blank string.",
        ),
        (
            {"conversationId": CID, "messages": [{"role": "user", "content": "x" * 4001}]},
            "A message content is limited to 4000 characters.",
        ),
        (
            {"conversationId": CID, "messages": [{"role": "assistant", "content": "x"}]},
            "The last message must be from the user.",
        ),
        (
            {"conversationId": CID, "messages": [{"role": "user", "content": "x"}], "model": 5},
            "model must be a string.",
        ),
    ],
)
def test_a_bad_turn_is_422_with_a_short_detail(body, detail):
    response = client(FakeMemory()).post("/api/v1/chat/memory", json=body)
    assert (response.status_code, response.json()) == (422, {"detail": detail})


def test_invalid_json_is_422():
    response = client(FakeMemory()).post(
        "/api/v1/chat/memory", content=b"{nope", headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, response.json()) == (
        422,
        {"detail": "The body is not valid JSON."},
    )


def test_unavailable_is_503_with_its_message_and_anything_else_is_a_fixed_message():
    turn = {"conversationId": CID, "messages": [{"role": "user", "content": "x"}]}
    one = client(FakeMemory(UnavailableError("OPENROUTER_API_KEY is not set."))).post(
        "/api/v1/chat/memory", json=turn
    )
    assert (one.status_code, one.json()["detail"]) == (503, "OPENROUTER_API_KEY is not set.")
    two = client(FakeMemory(RuntimeError("http://secret-host/leak"))).post(
        "/api/v1/chat/memory", json=turn
    )
    assert two.status_code == 503 and "secret" not in two.text
