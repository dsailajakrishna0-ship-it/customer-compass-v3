"""Test doubles for the model.

The agents' replies are built from the real `Recommendation` and `Review` types, so a test cannot
drift from what the parsers expect by mistyping JSON, and the fake answers by the agent's **role**
(which travels with every model call), never by looking for words in the system prompt. Rewording a
prompt can therefore not silently route a test to the wrong canned reply.

Raw strings are accepted wherever a typed reply is, for the tests that need malformed model output.
"""

import json
from collections.abc import Sequence

from app.agent.agents import AgentRole, Recommendation, Review
from app.llm.types import ChatMessage, GenerationResult


def model_result(text: str, model: str = "fake") -> GenerationResult:
    return GenerationResult(
        content=text,
        model=model,
        tokens_in=1,
        tokens_out=1,
        latency_ms=1,
        estimated_cost=None,
    )


def recommendation_text(recommendation: Recommendation) -> str:
    return json.dumps(
        {
            "action": recommendation.action,
            "rationale": recommendation.rationale,
            "evidence": recommendation.evidence,
        }
    )


def review_text(review: Review) -> str:
    return json.dumps({"verdict": review.verdict, "reasons": review.reasons})


def draft_text(note: str) -> str:
    return json.dumps({"task_note": note})


class FakeAgentModel:
    """Stands in for the model behind the agent workflow.

    `reviews` are returned in order; the last one repeats. `calls` records which agents were asked,
    and `prompts` the user message each one received, so a test can check what reached the model.
    """

    def __init__(
        self,
        analyst: Recommendation | str,
        reviews: Sequence[Review | str],
        draft: str = "Send pricing breakdown to Acme",
    ) -> None:
        self._analyst = analyst
        self._reviews = list(reviews)
        self._draft = draft
        self.calls: list[AgentRole] = []
        self.prompts: dict[AgentRole, list[str]] = {}

    async def __call__(
        self, role: AgentRole, _system_prompt: str, messages: list[ChatMessage]
    ) -> GenerationResult:
        self.calls.append(role)
        self.prompts.setdefault(role, []).append(messages[0]["content"])
        if role == "analyst":
            reply = self._analyst
            return model_result(reply if isinstance(reply, str) else recommendation_text(reply))
        if role == "reviewer":
            review = self._reviews.pop(0) if len(self._reviews) > 1 else self._reviews[0]
            return model_result(review if isinstance(review, str) else review_text(review))
        return model_result(draft_text(self._draft))


def constant_model(reply: str):
    """A model that answers every agent with the same raw text."""

    async def llm(_role: AgentRole, _system_prompt: str, _messages: list[ChatMessage]):
        return model_result(reply)

    return llm
