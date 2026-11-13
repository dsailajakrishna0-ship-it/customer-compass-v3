"""Stage 5.2: the only file that imports DeepEval (installed by `just eval-judged`, not by default).

DeepEval writes the judge prompts and does the arithmetic (it breaks an answer into claims, asks the
judge about each, and turns the verdicts into a 0 to 1 score). We only supply the judge: a model class
that sends every prompt through `judge.Judge`, so the pinned model and the record-and-replay cache
sit under all of it.
"""

from __future__ import annotations

import os

# Set before deepeval is imported: no telemetry, no cloud, no files written in the repo.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_GRPC_LOGGING", "NO")

from deepeval.metrics import (  # noqa: E402
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    FaithfulnessMetric,
)
from deepeval.models import DeepEvalBaseLLM  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402
from judge import Judge, extract_json  # noqa: E402


class CachedJudgeModel(DeepEvalBaseLLM):
    def __init__(self, judge: Judge) -> None:
        self.judge = judge
        super().__init__(model=judge.model)

    def load_model(self):  # nothing to load: the model is a hosted API behind the cache
        return self.judge

    def generate(self, prompt: str, schema=None, **_kwargs):
        text = self.judge.complete(prompt)
        if schema is None:
            return text
        return schema.model_validate(extract_json(text))

    async def a_generate(self, prompt: str, schema=None, **kwargs):
        return self.generate(prompt, schema, **kwargs)

    def get_model_name(self, *args, **kwargs) -> str:
        return self.judge.model


def score_case(judge: Judge, case: dict) -> dict[str, float]:
    """The four judged scores (0 to 1) for one recorded answer."""
    model = CachedJudgeModel(judge)
    test_case = LLMTestCase(
        input=case["question"],
        actual_output=case["answer"],
        expected_output=case["reference"],
        retrieval_context=case["contexts"],
    )
    # include_reason=False skips the explanation call, async_mode=False keeps calls in a fixed order
    # (the replay cache does not care about order, the free tier's rate limit does).
    common = {"model": model, "include_reason": False, "async_mode": False}
    metrics = {
        "faithfulness": FaithfulnessMetric(**common),
        "answer_relevancy": AnswerRelevancyMetric(**common),
        "context_precision": ContextualPrecisionMetric(**common),
        "context_recall": ContextualRecallMetric(**common),
    }
    scores: dict[str, float] = {}
    for name, metric in metrics.items():
        metric.measure(test_case)
        scores[name] = round(float(metric.score), 3)
    return scores
