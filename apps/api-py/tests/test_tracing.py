"""Stage 5.1 tracing (ADR 0022): spans are made for requests, model calls, retrieval and tool calls;
tracing is off by default; it never breaks the code it watches; and no secret or content goes into
a span unless content capture is on. Everything uses OpenTelemetry's in-memory exporter, so nothing
here needs a network or Langfuse."""

import base64
import json
import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app import tracing
from app.config import reset_settings
from app.llm import gateway
from app.llm.types import GenerationResult, ToolCall
from app.middleware import RequestIdMiddleware
from app.rag import retrieve
from app.rag.retrieve import RetrievedChunk
from app.routes import chat


@pytest.fixture
def spans():
    """Tracing on, spans kept in memory; off again afterwards."""
    exporter = InMemorySpanExporter()
    tracing.install(exporter)
    yield exporter
    tracing.shutdown_tracing()


def by_name(exporter: InMemorySpanExporter) -> dict:
    return {s.name: s for s in exporter.get_finished_spans()}


# ---------------------------------------------------------------- off by default, never breaks


def test_tracing_is_off_unless_it_is_switched_on(monkeypatch):
    monkeypatch.delenv("TRACING_ENABLED", raising=False)
    reset_settings()
    tracing.configure_tracing()

    assert tracing.tracing_active() is False
    with tracing.span("anything", "span", {"a": 1}) as handle:
        handle.set({"b": 2})
        handle.fail("nothing happens")
    assert handle is tracing.NO_SPAN


def test_the_code_being_traced_runs_and_its_errors_pass_through_unchanged(spans):
    with pytest.raises(ZeroDivisionError):
        with tracing.span("boom"):
            raise ZeroDivisionError("the message must not reach the span")
    finished = by_name(spans)["boom"]
    assert finished.status.status_code == StatusCode.ERROR
    assert finished.status.description == "ZeroDivisionError"  # the type, never the message


def test_a_broken_tracer_does_not_break_the_request(spans, monkeypatch):
    def refuse(*_a, **_k):
        raise RuntimeError("tracer is broken")

    monkeypatch.setattr(tracing._tracer, "start_as_current_span", refuse)
    with tracing.span("still runs") as handle:
        result = 2 + 2
    assert result == 4
    assert handle is tracing.NO_SPAN


def test_an_exporter_that_fails_does_not_break_the_request(monkeypatch):
    class Dead(SpanExporter):
        def export(self, spans):  # noqa: ARG002
            raise ConnectionError("langfuse is down")

        def shutdown(self):
            pass

    tracing.install(Dead())
    try:
        with tracing.span("work", "span", {"n": 1}):
            value = "done"
    finally:
        tracing.shutdown_tracing()
    assert value == "done"


# ---------------------------------------------------------------- what goes into a span


def test_spans_nest_and_carry_the_langfuse_observation_type(spans):
    with tracing.span("outer", "agent", {"agent.steps": 3}):
        with tracing.span("inner", "tool"):
            pass
    finished = by_name(spans)
    assert finished["inner"].parent.span_id == finished["outer"].context.span_id
    assert finished["inner"].context.trace_id == finished["outer"].context.trace_id
    assert finished["outer"].attributes["langfuse.observation.type"] == "agent"
    assert finished["outer"].attributes["agent.steps"] == 3
    assert finished["inner"].attributes["langfuse.observation.type"] == "tool"


def test_attributes_are_cleaned_secrets_dropped_and_text_shortened():
    clean = tracing.clean_attributes(
        {
            "openrouter_api_key": "sk-or-v1-abc",
            "Authorization": "Basic abc",
            "password": "x",
            "tokens": 12,
            "flag": True,
            "ratio": 0.5,
            "missing": None,
            "long": "word " * 100,
            "names": ["a", "b"],
        }
    )
    assert "openrouter_api_key" not in clean
    assert "Authorization" not in clean
    assert "password" not in clean
    assert "missing" not in clean
    assert clean["tokens"] == 12 and clean["flag"] is True and clean["ratio"] == 0.5
    assert len(clean["long"]) <= tracing.MAX_TEXT and clean["long"].endswith("…")
    assert clean["names"] == ["a", "b"]


def test_a_request_id_that_is_a_trace_id_becomes_the_trace_id():
    rid = "0123456789abcdef0123456789abcdef"
    assert tracing.trace_id_for_request_id(rid) == int(rid, 16)
    assert tracing.trace_id_for_request_id("my-own-token") is None  # not 32 hex characters
    assert tracing.trace_id_for_request_id("0" * 32) is None  # all zeros is not a valid trace id
    assert tracing.trace_id_for_request_id(rid.upper()) is None  # ids are lower-case hex


def test_a_forced_trace_id_applies_to_the_root_span_only(spans):
    forced = int("abcdef0123456789abcdef0123456789", 16)
    with tracing.span("root", trace_id=forced):
        with tracing.span("child"):
            pass
    with tracing.span("other"):
        pass

    finished = by_name(spans)
    assert finished["root"].context.trace_id == forced
    assert finished["root"].parent is None  # a true root, not a child of a made-up parent
    assert finished["child"].context.trace_id == forced
    assert finished["other"].context.trace_id != forced  # the next trace is random again


# ---------------------------------------------------------------- the request span


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping():
        with tracing.span("inside the request", "span"):
            return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/fail")
    async def fail():
        raise RuntimeError("secret detail that must not be in the span")

    return app


async def get(path: str, headers: dict | None = None):
    transport = ASGITransport(app=make_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers or {})


@pytest.mark.asyncio
async def test_a_request_is_one_trace_whose_id_is_the_request_id(spans):
    rid = "0123456789abcdef0123456789abcdef"

    response = await get("/ping", {"X-Request-ID": rid})

    assert response.headers["x-request-id"] == rid
    finished = by_name(spans)
    request_span, inner = finished["GET /ping"], finished["inside the request"]
    assert format(request_span.context.trace_id, "032x") == rid
    assert inner.context.trace_id == request_span.context.trace_id
    assert request_span.parent is None
    assert request_span.attributes["http.response.status_code"] == 200
    assert request_span.attributes["request.id"] == rid
    assert request_span.attributes["langfuse.trace.name"] == "GET /ping"


@pytest.mark.asyncio
async def test_a_callers_own_token_stays_an_attribute_and_the_trace_gets_a_fresh_id(spans):
    await get("/ping", {"X-Request-ID": "my-own-token"})

    request_span = by_name(spans)["GET /ping"]
    assert request_span.attributes["request.id"] == "my-own-token"
    assert format(request_span.context.trace_id, "032x") != "my-own-token"


@pytest.mark.asyncio
async def test_the_health_check_is_not_traced(spans):
    await get("/health")
    assert spans.get_finished_spans() == ()


@pytest.mark.asyncio
async def test_a_failing_request_is_an_error_span_without_the_exception_text(spans):
    response = await get("/fail")

    assert response.status_code == 500
    request_span = by_name(spans)["GET /fail"]
    assert request_span.status.status_code == StatusCode.ERROR
    assert "secret detail" not in json.dumps(dict(request_span.attributes))
    assert "secret detail" not in (request_span.status.description or "")


@pytest.mark.asyncio
async def test_requests_still_work_with_tracing_off():
    response = await get("/ping", {"X-Request-ID": "abc"})
    assert response.status_code == 200 and response.json() == {"ok": True}


# ---------------------------------------------------------------- the model call


def result(**kw) -> GenerationResult:
    base = dict(
        content="The answer text.",
        model="google/answering:free",
        tokens_in=40,
        tokens_out=9,
        latency_ms=1234,
        estimated_cost=0.0,
        fallback_used=True,
        fallback_from_model="google/first:free",
    )
    return GenerationResult(**{**base, **kw})


@pytest.mark.asyncio
async def test_a_model_call_is_a_generation_span_with_usage_and_no_text(spans, monkeypatch):
    async def fake(*_a, **_k):
        return result()

    monkeypatch.setattr(gateway, "_generate", fake)

    out = await gateway.generate(
        "system", [{"role": "user", "content": "Private question?"}], "m:free"
    )

    assert out.content == "The answer text."
    span = by_name(spans)["llm.generate"]
    assert span.attributes["langfuse.observation.type"] == "generation"
    assert span.attributes["gen_ai.request.model"] == "m:free"
    assert span.attributes["gen_ai.response.model"] == "google/answering:free"
    assert span.attributes["gen_ai.usage.input_tokens"] == 40
    assert span.attributes["gen_ai.usage.output_tokens"] == 9
    assert span.attributes["llm.latency_ms"] == 1234
    assert span.attributes["llm.fallback_used"] is True
    assert span.attributes["llm.fallback_from"] == "google/first:free"
    dumped = json.dumps(dict(span.attributes))
    assert "Private question" not in dumped and "The answer text" not in dumped


@pytest.mark.asyncio
async def test_content_is_recorded_only_when_capture_is_switched_on(spans, monkeypatch):
    async def fake(*_a, **_k):
        return result()

    monkeypatch.setattr(gateway, "_generate", fake)
    monkeypatch.setenv("TRACING_CAPTURE_CONTENT", "true")
    reset_settings()
    try:
        await gateway.generate(
            "system", [{"role": "user", "content": "Private question?"}], "m:free"
        )
    finally:
        monkeypatch.delenv("TRACING_CAPTURE_CONTENT")
        reset_settings()

    span = by_name(spans)["llm.generate"]
    assert span.attributes["langfuse.observation.input"] == "Private question?"
    assert span.attributes["langfuse.observation.output"] == "The answer text."


@pytest.mark.asyncio
async def test_a_failed_model_call_is_an_error_span_and_the_error_still_propagates(
    spans, monkeypatch
):
    async def boom(*_a, **_k):
        raise gateway.LlmUnavailableError("the chain is down")

    monkeypatch.setattr(gateway, "_generate", boom)

    with pytest.raises(gateway.LlmUnavailableError):
        await gateway.generate("s", [{"role": "user", "content": "q"}], "m:free")

    assert by_name(spans)["llm.generate"].status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------- retrieval


def chunk(similarity: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        document_id=1,
        document_title="Confidential contract",
        source_path="sample-data/documents/x.md",
        doc_type="email",
        company_name="Acme",
        chunk_index=0,
        content="Full private document text.",
        similarity=similarity,
    )


@pytest.mark.asyncio
async def test_a_retrieval_is_a_span_with_counts_and_similarity_but_no_text(spans, monkeypatch):
    async def fake(*_a, **_k):
        return [chunk(0.81), chunk(0.52)]

    monkeypatch.setattr(retrieve, "_retrieve_relevant_chunks", fake)

    found = await retrieve.retrieve_relevant_chunks("a private question", company_id=7, top_k=4)

    assert len(found) == 2
    span = by_name(spans)["retrieval"]
    assert span.attributes["langfuse.observation.type"] == "retriever"
    assert span.attributes["retrieval.results"] == 2
    assert span.attributes["retrieval.similarity_max"] == 0.81
    assert span.attributes["retrieval.similarity_min"] == 0.52
    assert span.attributes["retrieval.company_scoped"] is True
    assert span.attributes["retrieval.query_chars"] == len("a private question")
    dumped = json.dumps(dict(span.attributes))
    assert "private question" not in dumped and "Full private document text" not in dumped
    assert "Confidential contract" not in dumped


@pytest.mark.asyncio
async def test_a_retrieval_that_finds_nothing_has_no_similarity_attributes(spans, monkeypatch):
    async def fake(*_a, **_k):
        return []

    monkeypatch.setattr(retrieve, "_retrieve_relevant_chunks", fake)

    await retrieve.retrieve_relevant_chunks("q")

    span = by_name(spans)["retrieval"]
    assert span.attributes["retrieval.results"] == 0
    assert "retrieval.similarity_max" not in span.attributes


# ---------------------------------------------------------------- a tool call


@pytest.mark.asyncio
async def test_a_tool_call_is_a_span_with_argument_names_never_values(spans, monkeypatch):
    async def fake_call(_session, _name, _arguments):
        return json.dumps({"status": "executed", "companyName": "Acme Fabrication"})

    monkeypatch.setattr(chat, "call_tool", fake_call)
    used: list[dict] = []
    call = ToolCall(id="c1", name="get_open_deals", arguments={"company_name": "Acme Fabrication"})

    text = await chat._run_tool_call(None, call, False, used, "fastmcp")

    assert json.loads(text)["status"] == "executed"
    span = by_name(spans)["tool.get_open_deals"]
    assert span.attributes["langfuse.observation.type"] == "tool"
    assert span.attributes["tool.mcp_server"] == "fastmcp"
    assert list(span.attributes["tool.argument_names"]) == ["company_name"]
    assert span.attributes["tool.result_status"] == "executed"
    assert "Acme Fabrication" not in json.dumps(dict(span.attributes))


@pytest.mark.asyncio
async def test_a_task_call_records_whether_the_user_confirmed(spans, monkeypatch):
    async def fake_call(_s, _n, _a):
        return json.dumps({"status": "proposed"})

    monkeypatch.setattr(chat, "call_tool", fake_call)
    call = ToolCall(
        id="c", name="create_followup_task", arguments={"company_name": "Acme", "note": "Call"}
    )

    await chat._run_tool_call(None, call, False, [], "fastmcp")
    await chat._run_tool_call(None, call, True, [], "fastmcp")

    confirms = [s.attributes["tool.confirm"] for s in spans.get_finished_spans()]
    assert confirms == [False, True]


@pytest.mark.asyncio
async def test_a_tool_that_raises_is_an_error_span_and_a_result_the_model_can_read(
    spans, monkeypatch
):
    async def boom(*_a):
        raise RuntimeError("the tool server fell over")

    monkeypatch.setattr(chat, "call_tool", boom)
    call = ToolCall(id="c", name="get_open_deals", arguments={"company_name": "Acme"})

    text = await chat._run_tool_call(None, call, False, [], "fastmcp")

    assert json.loads(text)["status"] == "error"
    assert by_name(spans)["tool.get_open_deals"].status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
async def test_a_call_that_is_refused_before_it_runs_makes_no_tool_span(spans):
    call = ToolCall(id="c", name="get_open_deals", arguments={})  # missing company_name

    text = await chat._run_tool_call(None, call, False, [], "fastmcp")

    assert json.loads(text)["status"] == "error"
    assert spans.get_finished_spans() == ()


# ---------------------------------------------------------------- start-up wiring


def test_start_up_builds_the_langfuse_exporter_from_the_settings(monkeypatch, caplog):
    seen: dict = {}

    class FakeExporter(SpanExporter):
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def export(self, spans):  # noqa: ARG002
            return SpanExportResult.SUCCESS

        def shutdown(self):
            pass

    import opentelemetry.exporter.otlp.proto.http.trace_exporter as module

    monkeypatch.setattr(module, "OTLPSpanExporter", FakeExporter)
    monkeypatch.setenv("TRACING_ENABLED", "true")
    monkeypatch.setenv("TRACING_ENDPOINT", "http://langfuse-web:3000/api/public/otel/")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test-secret-value")
    reset_settings()
    try:
        with caplog.at_level(logging.DEBUG):
            tracing.configure_tracing()
        assert tracing.tracing_active() is True
    finally:
        tracing.shutdown_tracing()
        reset_settings()

    assert seen["endpoint"] == "http://langfuse-web:3000/api/public/otel/v1/traces"
    token = base64.b64encode(b"pk-lf-test:sk-lf-test-secret-value").decode()
    assert seen["headers"]["Authorization"] == f"Basic {token}"
    assert seen["headers"]["x-langfuse-ingestion-version"] == "4"
    assert "sk-lf-test-secret-value" not in caplog.text


def test_without_keys_no_authorization_header_is_sent(monkeypatch):
    seen: dict = {}

    class FakeExporter(SpanExporter):
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def export(self, spans):  # noqa: ARG002
            return SpanExportResult.SUCCESS

        def shutdown(self):
            pass

    import opentelemetry.exporter.otlp.proto.http.trace_exporter as module

    monkeypatch.setattr(module, "OTLPSpanExporter", FakeExporter)
    monkeypatch.setenv("TRACING_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    reset_settings()
    try:
        tracing.configure_tracing()
    finally:
        tracing.shutdown_tracing()
        reset_settings()

    assert "Authorization" not in seen["headers"]


def test_a_start_up_failure_is_logged_and_never_raised(monkeypatch):
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as module

    def refuse(**_kwargs):
        raise ValueError("bad endpoint")

    monkeypatch.setattr(module, "OTLPSpanExporter", refuse)
    monkeypatch.setenv("TRACING_ENABLED", "true")
    reset_settings()
    try:
        tracing.configure_tracing()  # must not raise
        assert tracing.tracing_active() is False
    finally:
        tracing.shutdown_tracing()
        reset_settings()
