"""Stage 5.1 tracing: every request becomes a trace, every model call, retrieval, tool call and agent
step becomes a span inside it (ADR 0022).

A *trace* is the story of one request; a *span* is one timed step in that story. We create them with
OpenTelemetry, the standard for this, and send them to Langfuse (or any OTLP receiver) in a background
thread. The audit tables stay as they are: they record *what was done* for accountability; a trace
records *how it went* (which model, how long, how many tokens, which step failed).

Three rules, the same as for the reranker (app/rag/rerank.py):

1. **Off by default.** With `TRACING_ENABLED=false` every function here does nothing and the app needs
   no tracing service, package setup or network.
2. **Tracing must never break a request.** Every call into OpenTelemetry is wrapped; a slow or dead
   receiver is the exporter thread's problem, never the request's. An exception raised by the code being
   traced is passed through untouched.
3. **Attributes are counts, names and sizes, not content.** No key, prompt or document text goes into a
   span unless `TRACING_CAPTURE_CONTENT=true`, and even then text is shortened. Anything that looks like
   a secret is dropped.
"""

import base64
import contextvars
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.config import get_settings

log = logging.getLogger("app.tracing")

# How Langfuse labels a step: `langfuse.observation.type` (generation, tool, retriever, agent, span ...)
OBSERVATION_TYPE = "langfuse.observation.type"
MAX_TEXT = 200
_SECRET_KEY = re.compile(
    r"api[_-]?key|secret|password|authorization|bearer|credential", re.IGNORECASE
)
_HEX_ID = re.compile(r"^[0-9a-f]{32}$")

_provider: TracerProvider | None = None
_tracer: trace.Tracer | None = None

# The trace id the next root span must use (set around the start of a request's span, see span()).
_forced_trace_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "forced_trace_id", default=None
)


class _RequestTraceIds(IdGenerator):
    """Random ids, except that a request's root span takes the request id as its trace id."""

    def __init__(self) -> None:
        self._random = RandomIdGenerator()

    def generate_span_id(self) -> int:
        return self._random.generate_span_id()

    def generate_trace_id(self) -> int:
        forced = _forced_trace_id.get()
        return forced if forced else self._random.generate_trace_id()


def tracing_active() -> bool:
    return _tracer is not None


# ---------------------------------------------------------------- set-up and tear-down


def configure_tracing() -> None:
    """Starts tracing when TRACING_ENABLED is true. Called once at start-up; never raises."""
    settings = get_settings()
    if not settings.tracing_enabled:
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        headers = {"x-langfuse-ingestion-version": "4"}
        public, secret = (
            settings.langfuse_public_key.get_secret_value(),
            settings.langfuse_secret_key.get_secret_value(),
        )
        if public and secret:
            token = base64.b64encode(f"{public}:{secret}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        exporter = OTLPSpanExporter(
            endpoint=settings.tracing_endpoint.rstrip("/") + "/v1/traces",
            headers=headers,
            timeout=int(settings.tracing_export_timeout_seconds),
        )
        install(exporter, batch=True)
        log.info("tracing_enabled endpoint=%s", settings.tracing_endpoint)
    except Exception:  # noqa: BLE001 - tracing must never stop the API from starting
        log.exception("tracing_setup_failed")


def install(exporter: SpanExporter, *, batch: bool = False) -> None:
    """Makes `exporter` receive every span. `batch` sends in the background (production); tests pass
    an in-memory exporter and read it straight away."""
    global _provider, _tracer
    shutdown_tracing()
    provider = TracerProvider(
        resource=Resource.create({"service.name": get_settings().tracing_service_name}),
        id_generator=_RequestTraceIds(),
    )
    provider.add_span_processor(
        BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter)
    )
    _provider = provider
    _tracer = provider.get_tracer("customer-compass")


def shutdown_tracing() -> None:
    """Flushes what is waiting and stops tracing (at shut-down, and between tests)."""
    global _provider, _tracer
    provider, _provider, _tracer = _provider, None, None
    if provider is not None:
        try:
            provider.shutdown()
        except Exception:  # noqa: BLE001
            log.exception("tracing_shutdown_failed")


# ---------------------------------------------------------------- safe attributes


def _shorten(text: str, limit: int = MAX_TEXT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clean_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Only values OpenTelemetry accepts, text shortened, and nothing that looks like a secret."""
    clean: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None or _SECRET_KEY.search(key):
            continue
        if isinstance(value, bool | int | float):
            clean[key] = value
        elif isinstance(value, list | tuple):
            clean[key] = [_shorten(str(item), 80) for item in value][:20]
        else:
            clean[key] = _shorten(str(value))
    return clean


def capture_content() -> bool:
    return get_settings().tracing_capture_content


# ---------------------------------------------------------------- spans


class SpanHandle:
    """What the code being traced sees: `set(...)` adds attributes, `fail(...)` marks an error. Every
    call is safe; with tracing off the handle does nothing."""

    def __init__(self, span: trace.Span | None = None):
        self._span = span

    def set(self, attributes: dict[str, Any]) -> None:
        if self._span is None:
            return
        try:
            for key, value in clean_attributes(attributes).items():
                self._span.set_attribute(key, value)
        except Exception:  # noqa: BLE001
            log.debug("span_attribute_failed", exc_info=True)

    def fail(self, error: BaseException | str) -> None:
        if self._span is None:
            return
        try:
            # the exception's type, not its message: a message can carry a key or a customer's text
            what = error if isinstance(error, str) else type(error).__name__
            self._span.set_status(Status(StatusCode.ERROR, _shorten(what, 80)))
        except Exception:  # noqa: BLE001
            log.debug("span_status_failed", exc_info=True)


NO_SPAN = SpanHandle()


@contextmanager
def span(
    name: str,
    kind: str = "span",
    attributes: dict[str, Any] | None = None,
    *,
    server: bool = False,
    trace_id: int | None = None,
) -> Iterator[SpanHandle]:
    """A timed step. Spans started inside it become its children. `kind` is Langfuse's observation type
    (span, generation, retriever, tool, agent). With `trace_id` a root span starts that trace. An
    exception from the body marks the span as failed and is raised again unchanged."""
    if _tracer is None:
        yield NO_SPAN
        return
    manager = None
    handle = NO_SPAN
    try:
        manager = _tracer.start_as_current_span(
            name,
            kind=SpanKind.SERVER if server else SpanKind.INTERNAL,
            record_exception=False,
            set_status_on_exception=False,
        )
        token = _forced_trace_id.set(trace_id) if trace_id else None
        try:
            handle = SpanHandle(manager.__enter__())  # the id generator runs here
        finally:
            if token is not None:
                _forced_trace_id.reset(token)
        handle.set({OBSERVATION_TYPE: kind, **(attributes or {})})
    except Exception:  # noqa: BLE001
        log.debug("span_start_failed", exc_info=True)
        manager, handle = None, NO_SPAN
    try:
        yield handle
    except BaseException as error:
        handle.fail(error)
        raise
    finally:
        if manager is not None:
            try:
                manager.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                log.debug("span_end_failed", exc_info=True)


def record_finished_span(
    name: str,
    kind: str,
    duration_ms: int,
    attributes: dict[str, Any] | None = None,
    error: bool = False,
) -> None:
    """A step that has already happened (the agent's trace records steps after they run): a child of
    whatever span is current, back-dated by its duration."""
    if _tracer is None:
        return
    try:
        end = time.time_ns()
        started = _tracer.start_span(name, start_time=end - max(duration_ms, 0) * 1_000_000)
        handle = SpanHandle(started)
        handle.set({OBSERVATION_TYPE: kind, **(attributes or {})})
        if error:
            handle.fail("step failed")
        started.end(end_time=end)
    except Exception:  # noqa: BLE001
        log.debug("finished_span_failed", exc_info=True)


def trace_id_for_request_id(request_id: str) -> int | None:
    """The trace id a request should use: its own request id, so one id finds the log lines, the
    X-Request-ID header and the trace in Langfuse. Only a 32-character hex id can be a trace id;
    anything else (a caller's own token) gets a fresh trace id and the request id stays an attribute."""
    if not _HEX_ID.match(request_id) or int(request_id, 16) == 0:
        return None
    return int(request_id, 16)
