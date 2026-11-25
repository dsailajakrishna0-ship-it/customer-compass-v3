"""The HTTP face every approach shares: POST /api/v1/chat/tools with the same body and the same
answer shape as the application's tool-calling route, plus GET /health.

Differences from the application's route, on purpose: it takes only the fields messages and model
(no mcpServer), it does not run the prompt guard (so the answer has no `guardrail`), and a bad
request gets a short `detail` message, not FastAPI's full validation list. What differs between
the approaches is only the ToolChat behind it.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .chat import Message, ToolChat, UnavailableError
from .telemetry import Telemetry

MAX_MESSAGES = 12
MAX_CONTENT_CHARACTERS = 4_000


def parse_messages(body: Any) -> list[Message]:
    """1 to 12 messages, a role of user or assistant, content that is not blank and at most 4,000
    characters, the last one from the user. Raises ValueError with a message for the client."""
    if not isinstance(body, dict):
        raise ValueError("The body must be a JSON object.")
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
        if len(content) > MAX_CONTENT_CHARACTERS:
            raise ValueError(
                f"A message content is limited to {MAX_CONTENT_CHARACTERS} characters."
            )
        messages.append(Message(role, content))
    if messages[-1].role != "user":
        raise ValueError("The last message must be from the user.")
    return messages


def parse_model(body: dict[str, Any]) -> str | None:
    model = body.get("model")
    if model is None:
        return None
    if not isinstance(model, str):
        raise ValueError("model must be a string.")
    return model if model.strip() else None


def create_app(chat: ToolChat, telemetry: Telemetry | None = None) -> FastAPI:
    app = FastAPI(title=f"Comparison backend: {chat.approach}", docs_url=None, redoc_url=None)
    # The browser app runs on another port, so every answer says it may be read.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "approach": chat.approach}

    @app.get("/api/v1/observability/recent")
    def recent() -> JSONResponse:
        """The most recent traces and the metrics; 404 with a hint when observation is off."""
        if telemetry is None:
            return JSONResponse(
                {
                    "enabled": False,
                    "detail": "Observation is off. Start the backend with TELEMETRY_ENABLED=true.",
                },
                status_code=404,
            )
        return JSONResponse(telemetry.recent_json())

    @app.post("/api/v1/chat/tools")
    async def tools(request: Request) -> JSONResponse:
        try:
            body = json.loads((await request.body()).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"detail": "The body is not valid JSON."}, status_code=422)
        try:
            messages = parse_messages(body)
            model = parse_model(body)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        try:
            result = await run_in_threadpool(chat.answer, messages, model)
        except UnavailableError as exc:
            return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=503)
        except Exception:  # noqa: BLE001 - never leak a library's own message
            message = "Could not answer using tools."
            return JSONResponse({"error": message, "detail": message}, status_code=503)
        usage = result.usage
        return JSONResponse(
            {
                "message": result.message,
                "toolsUsed": [
                    {"tool": use.tool, "arguments": use.arguments} for use in result.tools_used
                ],
                "mcpServer": chat.approach,
                "usage": {
                    "model": usage.model if usage else None,
                    "tokensIn": usage.tokens_in if usage else None,
                    "tokensOut": usage.tokens_out if usage else None,
                    "latencyMs": usage.latency_ms if usage else 0,
                    "estimatedCost": None,
                    "fallbackUsed": False,
                    "fallbackFromModel": None,
                },
            }
        )

    return app
