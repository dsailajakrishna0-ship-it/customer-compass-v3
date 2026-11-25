"""What the observed variant of a tool-calling approach shares: one observed request per question,
opened before the answer and closed after it (also when it fails). How the events of the answer are
captured is the approach's own business (callbacks, stream events); this only wires the request."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from .chat import Message, Result, UnavailableError
from .telemetry import ChatObserver, NoObserver, ObservedRequest

CURRENT: ContextVar[tuple[ObservedRequest, str] | None] = ContextVar(
    "observed_request", default=None
)


class ObservedMixin:
    """Put before the approach class: `class Observed(ObservedMixin, LangChainToolChat)`."""

    _observer: ChatObserver = NoObserver()
    _default_model: str

    def observe_with(self, observer: ChatObserver) -> None:
        self._observer = observer

    def answer(self, messages: list[Message], model: str | None) -> Result:
        request = self._observer.begin(self.approach, model)  # type: ignore[attr-defined]
        token = CURRENT.set((request, model or self._default_model))
        try:
            return super().answer(messages, model)  # type: ignore[misc, no-any-return]
        except UnavailableError:
            request.fail("model_unavailable")
            raise
        except Exception:
            request.fail("error")
            raise
        finally:
            CURRENT.reset(token)
            request.close()


def offered_names(tools: list[Any]) -> set[str]:
    return {t.name for t in tools}
