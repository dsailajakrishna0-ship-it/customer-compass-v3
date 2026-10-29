"""Structured logs and request ids, exercised on a tiny app so no database is needed."""

import io
import json
import logging
import re

import httpx
import pytest
from fastapi import FastAPI

from app.logs import configure_logging
from app.middleware import REQUEST_ID_HEADER, RequestIdMiddleware


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping():
        logging.getLogger("app.demo").info("inside the handler")
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    return app


@pytest.fixture
def log_stream():
    stream = io.StringIO()
    configure_logging("INFO", "json", stream)
    yield stream
    configure_logging("INFO", "json")  # back to stderr for the other tests


def lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


async def get(app: FastAPI, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, **kwargs)


@pytest.mark.asyncio
async def test_every_response_carries_a_generated_request_id(log_stream):
    response = await get(make_app(), "/ping")
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers[REQUEST_ID_HEADER])


@pytest.mark.asyncio
async def test_a_plain_caller_id_is_kept_and_shows_in_every_log_line(log_stream):
    response = await get(make_app(), "/ping", headers={REQUEST_ID_HEADER: "client-abc.123"})
    assert response.headers[REQUEST_ID_HEADER] == "client-abc.123"
    records = lines(log_stream)
    assert {r["request_id"] for r in records} == {"client-abc.123"}
    # the standard-library logger used by the existing code is part of the same stream
    handler_line = next(r for r in records if r["event"] == "inside the handler")
    assert handler_line["logger"] == "app.demo" and handler_line["level"] == "info"
    summary = next(r for r in records if r["event"] == "request")
    assert summary["status"] == 200 and summary["path"] == "/ping" and "duration_ms" in summary


@pytest.mark.asyncio
async def test_an_unsafe_caller_id_is_replaced(log_stream):
    response = await get(make_app(), "/ping", headers={REQUEST_ID_HEADER: "bad id with spaces"})
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers[REQUEST_ID_HEADER])


@pytest.mark.asyncio
async def test_ids_do_not_leak_between_requests(log_stream):
    app = make_app()
    first = (await get(app, "/ping")).headers[REQUEST_ID_HEADER]
    second = (await get(app, "/ping")).headers[REQUEST_ID_HEADER]
    assert first != second
    ids = [r["request_id"] for r in lines(log_stream) if r["event"] == "request"]
    assert ids == [first, second]


@pytest.mark.asyncio
async def test_the_health_check_stays_out_of_the_info_logs(log_stream):
    await get(make_app(), "/health")
    assert lines(log_stream) == []


@pytest.mark.asyncio
async def test_a_crash_is_logged_with_the_request_id(log_stream):
    response = await get(make_app(), "/boom")
    assert response.status_code == 500
    failed = next(r for r in lines(log_stream) if r["event"] == "request_failed")
    assert failed["request_id"] and "kaboom" in failed["exception"]


@pytest.mark.asyncio
async def test_outgoing_http_calls_never_log_their_urls_so_api_keys_stay_out(log_stream):
    """The embeddings call passes the Google key as ?key=...; httpx would log that URL at INFO."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as client:
        await client.post("https://example.test/embed", params={"key": "SECRET-KEY-123"})
    assert "SECRET-KEY-123" not in log_stream.getvalue()
    assert log_stream.getvalue() == ""


def test_console_format_is_readable_text():
    stream = io.StringIO()
    configure_logging("INFO", "console", stream)
    logging.getLogger("app.demo").info("hello console")
    configure_logging("INFO", "json")
    assert "hello console" in stream.getvalue()
    with pytest.raises(json.JSONDecodeError):
        json.loads(stream.getvalue().splitlines()[0])
