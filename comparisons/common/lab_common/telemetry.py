"""Where an approach reports what it does while it answers one question, and the one place that
knows OpenTelemetry: the events become spans and metrics, and the most recent ones can be shown.

Spans, as in the application's tracing (ADR 0022): `chat.request` (the root, one per question),
`llm.generate` (one per model call, with the GenAI attributes) and `tool.<name>` (one per tool the
model asked for). The rule that holds for every approach: **names, counts, ids and durations only,
never content** (no question, prompt, answer, document text or tool argument value).
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Sequence
from typing import Any, Protocol

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

_NAME = re.compile(r"[a-z_]{1,40}")
CAPACITY = 200


class ObservedRequest(Protocol):
    def model_call(
        self,
        model: str | None,
        tokens_in: int | None,
        tokens_out: int | None,
        millis: int,
        outcome: str,
    ) -> None:
        """One call to the model. `outcome` is ok or error; tokens may be None."""

    def tool_call(self, tool: str, outcome: str, millis: int) -> None:
        """One tool the model asked for. `tool` is a name the backend offers, or unknown;
        `outcome` is ran, invalid_call, invalid_arguments, tool_error or skipped."""

    def fail(self, kind: str) -> None:
        """The question could not be answered; `kind` is a short word such as model_unavailable."""

    def close(self) -> None: ...


class ChatObserver(Protocol):
    def begin(self, approach: str, requested_model: str | None) -> ObservedRequest:
        """A question starts. Close the returned request when the answer is done (or failed)."""


class _NoRequest:
    def model_call(self, *args: Any, **kwargs: Any) -> None: ...
    def tool_call(self, *args: Any, **kwargs: Any) -> None: ...
    def fail(self, *args: Any, **kwargs: Any) -> None: ...
    def close(self) -> None: ...


class NoObserver:
    """What an approach uses when observation is off."""

    def begin(self, approach: str, requested_model: str | None) -> ObservedRequest:
        return _NoRequest()


class RecentSpans(SpanExporter):
    """Keeps only the most recent finished spans, so a long-running backend cannot fill its memory."""

    def __init__(self) -> None:
        self._spans: deque[ReadableSpan] = deque(maxlen=CAPACITY)
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def snapshot(self) -> list[ReadableSpan]:
        with self._lock:
            return list(self._spans)


class Telemetry:
    """Turns the events an approach reports into spans and metrics. In-process only."""

    def __init__(self, exporter: SpanExporter | None = None) -> None:
        self.recent = RecentSpans()
        self._provider = TracerProvider()
        self._provider.add_span_processor(SimpleSpanProcessor(exporter or self.recent))
        self._tracer = self._provider.get_tracer("comparisons")
        self._reader = InMemoryMetricReader()
        meter = MeterProvider(metric_readers=[self._reader]).get_meter("comparisons")
        self._requests = meter.create_counter("cc.chat.requests", description="Questions answered")
        self._model_calls = meter.create_counter(
            "cc.chat.model_calls", description="Calls to the model"
        )
        self._tool_calls = meter.create_counter(
            "cc.chat.tool_calls", description="Tools the model asked for"
        )
        self._tokens = meter.create_counter("gen_ai.client.token.usage", unit="{token}")
        self._duration = meter.create_histogram("cc.chat.request.duration", unit="ms")

    def begin(self, approach: str, requested_model: str | None) -> ObservedRequest:
        root = self._tracer.start_span(
            "chat.request",
            kind=trace.SpanKind.SERVER,
            attributes={
                "cc.approach": approach,
                "gen_ai.request.model": requested_model or "default",
            },
        )
        return _Handle(self, approach, root)

    def metrics(self) -> list[dict[str, Any]]:
        data = self._reader.get_metrics_data()
        out: list[dict[str, Any]] = []
        for resource in data.resource_metrics if data else []:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    points = [
                        {
                            "attributes": dict(p.attributes),
                            "value": getattr(p, "value", getattr(p, "sum", None)),
                        }
                        for p in metric.data.data_points
                    ]
                    out.append({"name": metric.name, "points": points})
        return out

    def recent_json(self) -> dict[str, Any]:
        traces: dict[str, list[dict[str, Any]]] = {}
        for span in self.recent.snapshot():
            trace_id = format(span.context.trace_id, "032x")
            traces.setdefault(trace_id, []).append(
                {
                    "name": span.name,
                    "durationMs": round((span.end_time - span.start_time) / 1_000_000),
                    "attributes": dict(span.attributes or {}),
                }
            )
        return {
            "enabled": True,
            "traces": [{"traceId": t, "spans": spans} for t, spans in traces.items()],
            "metrics": self.metrics(),
        }


class _Handle:
    def __init__(self, telemetry: Telemetry, approach: str, root: trace.Span) -> None:
        self._t = telemetry
        self._approach = approach
        self._root = root
        self._started = time.monotonic()
        self._models = 0
        self._tools = 0
        self._failure: str | None = None
        self._closed = False
        self._lock = threading.Lock()

    def _child(self, name: str, millis: int, attributes: dict[str, Any]) -> trace.Span:
        """A child span of the request, back-dated by the duration (the time was spent before the report)."""
        end = time.time_ns()
        ctx = trace.set_span_in_context(self._root, otel_context.Context())
        return self._t._tracer.start_span(
            name, context=ctx, start_time=end - max(0, millis) * 1_000_000, attributes=attributes
        )

    def model_call(
        self,
        model: str | None,
        tokens_in: int | None,
        tokens_out: int | None,
        millis: int,
        outcome: str,
    ) -> None:
        with self._lock:
            self._models += 1
            name = model or "unknown"
            attrs: dict[str, Any] = {
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": name,
                "cc.outcome": outcome,
            }
            if tokens_in is not None:
                attrs["gen_ai.usage.input_tokens"] = tokens_in
            if tokens_out is not None:
                attrs["gen_ai.usage.output_tokens"] = tokens_out
            span = self._child("llm.generate", millis, attrs)
            if outcome == "error":
                span.set_status(StatusCode.ERROR)
            span.end()
            self._t._model_calls.add(
                1,
                {
                    "cc.approach": self._approach,
                    "gen_ai.request.model": name,
                    "cc.outcome": outcome,
                },
            )
            if tokens_in is not None:
                self._t._tokens.add(
                    tokens_in, {"cc.approach": self._approach, "gen_ai.token.type": "input"}
                )
            if tokens_out is not None:
                self._t._tokens.add(
                    tokens_out, {"cc.approach": self._approach, "gen_ai.token.type": "output"}
                )

    def tool_call(self, tool: str, outcome: str, millis: int) -> None:
        with self._lock:
            self._tools += 1
            # only a fixed-shape name goes in: anything else is recorded as "unknown", never as given
            name = tool if _NAME.fullmatch(tool or "") else "unknown"
            span = self._child(
                f"tool.{name}", millis, {"gen_ai.tool.name": name, "cc.outcome": outcome}
            )
            if outcome != "ran":
                span.set_status(StatusCode.ERROR)
            span.end()
            self._t._tool_calls.add(
                1, {"cc.approach": self._approach, "gen_ai.tool.name": name, "cc.outcome": outcome}
            )

    def fail(self, kind: str) -> None:
        with self._lock:
            self._failure = kind

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            status = "ok" if self._failure is None else "error"
            self._root.set_attribute("cc.status", status)
            self._root.set_attribute("cc.model_calls", self._models)
            self._root.set_attribute("cc.tool_calls", self._tools)
            if self._failure is not None:
                self._root.set_attribute("cc.failure", self._failure)
                self._root.set_status(StatusCode.ERROR)
            self._root.end()
            self._t._requests.add(1, {"cc.approach": self._approach, "cc.status": status})
            self._t._duration.record(
                int((time.monotonic() - self._started) * 1000), {"cc.approach": self._approach}
            )
