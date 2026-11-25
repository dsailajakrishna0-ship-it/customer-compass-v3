"""What every agent approach implements, and the HTTP face they share.

A short run that looks up a company, asks the model for one recommended next action, **pauses for a
person's approval**, and then (approved) performs the action as a dry run: nothing is written
anywhere. The face is `POST /api/v1/agent/start` with `{"company": "Acme", "model": "optional"}`,
`POST /api/v1/agent/resume` with `{"runId": "...", "approve": true}` and `GET /health`. The
approaches differ only in how they keep the steps, the pause and the resume.
"""

from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .chat import UnavailableError

MAX_COMPANY = 200
MAX_MODEL = 100
MAX_RUNS = 100
RUN_ID = re.compile(r"[0-9a-fA-F-]{8,64}")
WAITING_MESSAGE = "Waiting for approval of the recommended action."
DECLINED_MESSAGE = "Declined. Nothing was done."


@dataclass(frozen=True)
class Recommendation:
    """One recommended next action and why, both short and already length-checked."""

    action: str
    rationale: str


@dataclass(frozen=True)
class Step:
    """`status` is done, waiting (for the person), pending, skipped or declined."""

    name: str
    status: str


@dataclass(frozen=True)
class Outcome:
    """Where a run is. `status` is awaiting_approval, completed or declined; `steps` are always
    gather, recommend, approval, act, in that order."""

    run_id: str
    status: str
    steps: list[Step]
    recommendation: Recommendation | None
    message: str


class CompanyNotFoundError(RuntimeError):
    """No company matches the name."""


class UnknownRunError(RuntimeError):
    """No run with that id (never started, or evicted: only the most recent runs are kept)."""


class NotAwaitingApprovalError(RuntimeError):
    """The run is not waiting for an answer (already answered)."""


class Agent(Protocol):
    approach: str

    def start(self, company: str, model: str | None) -> Outcome:
        """Runs the agent up to the approval pause and returns where it stopped."""
        ...

    def resume(self, run_id: str, approve: bool) -> Outcome:
        """Continues a paused run with the person's answer."""
        ...


def outcome_for(
    run_id: str, status: str, recommendation: Recommendation | None, message: str | None = None
) -> Outcome:
    """The four steps for a status; the same for every approach."""
    approval, act = {
        "completed": ("done", "done"),
        "declined": ("declined", "skipped"),
    }.get(status, ("waiting", "pending"))
    steps = [
        Step("gather", "done"),
        Step("recommend", "done"),
        Step("approval", approval),
        Step("act", act),
    ]
    return Outcome(run_id, status, steps, recommendation, message or WAITING_MESSAGE)


class BoundedRuns[T]:
    """The most recent MAX_RUNS runs, so a stream of starts cannot fill memory. `on_evict` is told
    which run id was dropped (an approach that keeps state elsewhere cleans it up there)."""

    def __init__(self, capacity: int = MAX_RUNS, on_evict=None) -> None:  # noqa: ANN001
        self._runs: OrderedDict[str, T] = OrderedDict()
        self._capacity = capacity
        self._on_evict = on_evict
        self._lock = threading.Lock()

    def put(self, run_id: str, run: T) -> None:
        with self._lock:
            self._runs[run_id] = run
            while len(self._runs) > self._capacity:
                evicted, _ = self._runs.popitem(last=False)
                if self._on_evict:
                    self._on_evict(evicted)

    def get(self, run_id: str) -> T | None:
        with self._lock:
            return self._runs.get(run_id)

    def __len__(self) -> int:
        return len(self._runs)


def _validate_start(body: dict) -> tuple[str, str | None]:
    company = body.get("company")
    if not isinstance(company, str) or not company.strip():
        raise ValueError("company is required and must be a non-blank string.")
    if len(company) > MAX_COMPANY:
        raise ValueError(f"company is limited to {MAX_COMPANY} characters.")
    model = body.get("model")
    if model is not None and (not isinstance(model, str) or len(model) > MAX_MODEL):
        raise ValueError(f"model must be a string of at most {MAX_MODEL} characters.")
    return company.strip(), (model if model and model.strip() else None)


def _validate_resume(body: dict) -> tuple[str, bool]:
    run_id = body.get("runId")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("runId is required and must be a run id.")
    approve = body.get("approve")
    if not isinstance(approve, bool):
        raise ValueError("approve is required and must be true or false.")
    return run_id, approve


def _view(outcome: Outcome) -> dict:
    view: dict = {
        "runId": outcome.run_id,
        "status": outcome.status,
        "steps": [{"name": s.name, "status": s.status} for s in outcome.steps],
    }
    if outcome.recommendation is not None:
        view["recommendation"] = {
            "action": outcome.recommendation.action,
            "rationale": outcome.recommendation.rationale,
        }
    view["message"] = outcome.message
    return view


def create_run_app(agent: Agent) -> FastAPI:
    app = FastAPI(title=f"Agent backend: {agent.approach}", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "approach": agent.approach}

    async def handle(request: Request, starting: bool) -> JSONResponse:
        try:
            body = json.loads((await request.body()).decode("utf-8") or "null")
            if not isinstance(body, dict):
                raise ValueError("The body must be a JSON object.")
            parsed = _validate_start(body) if starting else _validate_resume(body)
        except UnicodeDecodeError:
            return JSONResponse({"detail": "The body is not valid JSON."}, status_code=422)
        except json.JSONDecodeError:
            return JSONResponse({"detail": "The body is not valid JSON."}, status_code=422)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        try:
            call = agent.start if starting else agent.resume
            outcome = await run_in_threadpool(call, *parsed)
            return JSONResponse(_view(outcome))
        except (CompanyNotFoundError, UnknownRunError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=404)
        except NotAwaitingApprovalError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
        except UnavailableError as exc:
            return JSONResponse({"error": str(exc), "detail": str(exc)}, status_code=503)
        except Exception:  # noqa: BLE001 - never the exception's own text: it can carry a URL
            message = "The agent could not run."
            return JSONResponse({"error": message, "detail": message}, status_code=503)

    @app.post("/api/v1/agent/start")
    async def start(request: Request) -> JSONResponse:
        return await handle(request, True)

    @app.post("/api/v1/agent/resume")
    async def resume(request: Request) -> JSONResponse:
        return await handle(request, False)

    return app
