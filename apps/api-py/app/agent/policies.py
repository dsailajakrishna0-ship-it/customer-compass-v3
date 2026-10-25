"""Stage 10 policies: the hard limits and stop conditions around an agent
run, plus the rule that decides whether a message needs the agent at all.

The limits live in code, not in a prompt, so no model output can raise them.
Nothing here writes data: creating a task needs the separate confirm step.
"""

import os
import re
import time
from dataclasses import dataclass


class BudgetExceeded(Exception):
    """Raised when a run would exceed its step or time limit."""


@dataclass(frozen=True)
class AgentLimits:
    # A normal run is 6 steps (3 evidence + Analyst + Reviewer + Task Drafter);
    # a revision round adds 2 more (Analyst again, Reviewer again).
    max_steps: int = 8
    timeout_seconds: float = 180.0
    max_revisions: int = 1

    @classmethod
    def from_env(cls) -> "AgentLimits":
        return cls(
            max_steps=int(os.environ.get("AGENT_MAX_STEPS", "8")),
            timeout_seconds=float(os.environ.get("AGENT_TIMEOUT_SECONDS", "180")),
            max_revisions=int(os.environ.get("AGENT_MAX_REVISIONS", "1")),
        )


class RunBudget:
    """Counts steps and elapsed time for one run; `spend()` is called before
    every step and raises BudgetExceeded instead of letting a run go on."""

    def __init__(self, limits: AgentLimits):
        self.limits = limits
        self.steps_used = 0
        self._started = time.monotonic()

    def spend(self) -> None:
        if self.steps_used >= self.limits.max_steps:
            raise BudgetExceeded(f"step limit reached ({self.limits.max_steps})")
        if time.monotonic() - self._started > self.limits.timeout_seconds:
            raise BudgetExceeded(f"time limit reached ({self.limits.timeout_seconds:.0f}s)")
        self.steps_used += 1


# Routing: only "analyze / recommend / next action" requests need the agent.
# Plain factual questions stay on the direct SQL/RAG chat modes.
_AGENT_INTENT = re.compile(
    r"\b(analy[sz]e|analysis|recommend\w*|next (?:action|step)s?|follow[- ]?up|"
    r"what should we do|account review|review the account)\b",
    re.IGNORECASE,
)


def needs_agent(message: str) -> bool:
    return bool(_AGENT_INTENT.search(message))
