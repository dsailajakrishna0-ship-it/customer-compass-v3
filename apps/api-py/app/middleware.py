"""Request id middleware.

Every HTTP request gets an id: the caller's `X-Request-ID` if it is a plain token, otherwise a
fresh one. The id is bound to the logging context (so every log line of that request carries
it), returned in the `X-Request-ID` response header, and one summary line is logged when the
request ends. Later stages reuse the same id as the trace id.
"""

import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
# Accept only short plain tokens from callers, so a header cannot inject text into the logs
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

log = structlog.stdlib.get_logger("app.request")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode(), b"").decode()
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=scope["method"], path=scope["path"]
        )
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("request_failed")
            raise
        finally:
            # the health check is polled every few seconds; keep it out of the info logs
            level = "debug" if scope["path"] == "/health" else "info"
            getattr(log, level)(
                "request", status=status, duration_ms=round((time.perf_counter() - started) * 1000)
            )
            structlog.contextvars.clear_contextvars()
