import pytest
from fastapi.testclient import TestClient
from lab_common.chat import Message, Result, ToolUse, UnavailableError, Usage
from lab_common.server import MAX_CONTENT_CHARACTERS, create_app


class FakeChat:
    approach = "fake"

    def __init__(self, error=None):
        self.error = error
        self.received = None

    def answer(self, messages: list[Message], model):
        self.received = (messages, model)
        if self.error:
            raise self.error
        return Result(
            "hello", [ToolUse("get_open_deals", {"company_name": "Acme"})], Usage("m", 3, 4, 12)
        )


def post(chat, body):
    return TestClient(create_app(chat)).post("/api/v1/chat/tools", json=body)


def test_health_names_the_approach():
    assert TestClient(create_app(FakeChat())).get("/health").json() == {
        "status": "ok",
        "approach": "fake",
    }


def test_the_answer_has_the_application_shape():
    chat = FakeChat()
    response = post(chat, {"messages": [{"role": "user", "content": "hi"}], "model": "x/y"})
    assert response.status_code == 200
    assert response.json() == {
        "message": "hello",
        "toolsUsed": [{"tool": "get_open_deals", "arguments": {"company_name": "Acme"}}],
        "mcpServer": "fake",
        "usage": {
            "model": "m",
            "tokensIn": 3,
            "tokensOut": 4,
            "latencyMs": 12,
            "estimatedCost": None,
            "fallbackUsed": False,
            "fallbackFromModel": None,
        },
    }
    assert chat.received == ([Message("user", "hi")], "x/y")


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ([], "The body must be a JSON object."),
        ({}, "messages is required and must be a list."),
        ({"messages": []}, "messages must hold 1 to 12 items."),
        (
            {"messages": [{"role": "system", "content": "x"}]},
            "A message role must be user or assistant.",
        ),
        (
            {"messages": [{"role": "user", "content": "  "}]},
            "A message content must be a non-blank string.",
        ),
        (
            {"messages": [{"role": "user", "content": "x" * (MAX_CONTENT_CHARACTERS + 1)}]},
            f"A message content is limited to {MAX_CONTENT_CHARACTERS} characters.",
        ),
        (
            {"messages": [{"role": "assistant", "content": "x"}]},
            "The last message must be from the user.",
        ),
        ({"messages": [{"role": "user", "content": "x"}], "model": 5}, "model must be a string."),
    ],
)
def test_a_bad_request_gets_422_with_a_short_detail(body, detail):
    response = post(FakeChat(), body)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}


def test_invalid_json_is_422():
    response = TestClient(create_app(FakeChat())).post(
        "/api/v1/chat/tools", content=b"{nope", headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, response.json()) == (
        422,
        {"detail": "The body is not valid JSON."},
    )


def test_a_blank_model_means_the_backends_own_default():
    chat = FakeChat()
    post(chat, {"messages": [{"role": "user", "content": "hi"}], "model": "  "})
    assert chat.received[1] is None


def test_unavailable_is_503_with_its_message_and_anything_else_is_a_fixed_message():
    one = post(
        FakeChat(UnavailableError("The CRM could not be reached.")),
        {"messages": [{"role": "user", "content": "hi"}]},
    )
    assert (one.status_code, one.json()["detail"]) == (503, "The CRM could not be reached.")
    two = post(
        FakeChat(RuntimeError("secret library text")),
        {"messages": [{"role": "user", "content": "hi"}]},
    )
    assert two.status_code == 503 and "secret" not in two.text


def test_the_browser_app_may_read_every_answer():
    response = TestClient(create_app(FakeChat())).get(
        "/health", headers={"Origin": "http://localhost:5173"}
    )
    assert response.headers["access-control-allow-origin"] == "*"
