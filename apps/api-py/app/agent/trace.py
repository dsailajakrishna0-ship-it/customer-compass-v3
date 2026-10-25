"""Stage 10 execution trace: an inspectable record of every step an agent run
takes (which code step, tool or agent ran, what went in, what came out, how
long it took). It is returned to the UI so a human can see why the system
recommended what it did.
"""

import time
from dataclasses import asdict, dataclass, field
from typing import Literal

StepKind = Literal["code", "tool", "agent", "gate"]
StepStatus = Literal["ok", "error", "skipped"]

SUMMARY_MAX_CHARS = 300


def _shorten(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SUMMARY_MAX_CHARS else text[: SUMMARY_MAX_CHARS - 1] + "…"


@dataclass
class TraceStep:
    index: int
    kind: StepKind
    name: str
    input_summary: str
    output_summary: str
    status: StepStatus
    duration_ms: int


@dataclass
class Trace:
    steps: list[TraceStep] = field(default_factory=list)

    def record(
        self,
        kind: StepKind,
        name: str,
        input_summary: str,
        output_summary: str,
        started_at: float,
        status: StepStatus = "ok",
    ) -> TraceStep:
        """`started_at` is a time.monotonic() value taken before the step ran."""
        step = TraceStep(
            index=len(self.steps) + 1,
            kind=kind,
            name=name,
            input_summary=_shorten(input_summary),
            output_summary=_shorten(output_summary),
            status=status,
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
        self.steps.append(step)
        return step

    def to_list(self) -> list[dict]:
        return [asdict(step) for step in self.steps]
