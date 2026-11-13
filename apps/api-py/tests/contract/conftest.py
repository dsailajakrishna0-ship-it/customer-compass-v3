"""Fixtures for the API-contract tests.

A contract test drives the real application over HTTP (the real FastAPI app, the real Postgres with the
demo data) and checks only what a caller of the API can see. The one thing it replaces is everything
that needs the internet or a model, at exactly two documented seams (see tests/README.md):

1. the **model**: `app.routes.agent.make_llm` is replaced by a fake that answers by agent role;
2. **document retrieval**: `app.mcp.tools.retrieve_relevant_chunks` is replaced by canned chunks.

Only this file may name a seam. `tests/test_contract_boundary.py` fails if a contract test reaches
anywhere else, so these tests can keep passing unchanged while the code behind the API is rewritten.
"""

import json
import os
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from app.db import get_pool
from app.llm.gateway import LlmUnavailableError
from app.llm.types import GenerationResult, ToolCall
from app.main import app
from app.rag.embeddings import EmbeddingsUnavailableError

# The only things a contract test may replace. The boundary test checks this set against the code.
SEAMS = {"app.routes.agent.make_llm", "app.mcp.tools.retrieve_relevant_chunks"}

TEST_NOTE_PREFIX = "CONTRACT-TEST"

# Stage 5.5: the same contract suite runs against both sides of the agent seam (`AGENT_IMPL=frameworks just
# test-contract-frameworks`). Everything a caller can see is identical; the one inherent difference is that
# the prebuilt agent asks the model once more before the Analyst's answer (the turn in which the model
# chooses its evidence tools), so a test that lists the model calls uses `calls_for`.
AGENT_IMPL = os.environ.get("AGENT_IMPL", "manual")


def calls_for(*roles: str) -> list[str]:
    """The model calls expected for a run, given the manual agent's roles in order. On the prebuilt side
    the first Analyst turn is two calls (the model chooses tools, then answers); a revision is one."""
    if AGENT_IMPL != "frameworks":
        return list(roles)
    calls: list[str] = []
    for role in roles:
        first_analyst = role == "analyst" and "analyst" not in calls
        calls.extend(["analyst", "analyst"] if first_analyst else [role])
    return calls


def recommendation(action: str, rationale: str, evidence: list[str]) -> str:
    """What the Analyst agent's model reply looks like: JSON with these three keys (part of the model seam)."""
    return json.dumps({"action": action, "rationale": rationale, "evidence": evidence})


def review(verdict: str, reasons: list[str]) -> str:
    """What the Reviewer agent's model reply looks like: JSON with a verdict and reasons."""
    return json.dumps({"verdict": verdict, "reasons": reasons})


GOOD_RECOMMENDATION = recommendation(
    "Send the pricing breakdown", "They asked for pricing.", ["E1"]
)
APPROVE = review("approve", [])
REVISE = review("revise", ["too vague"])


def reply(text: str) -> GenerationResult:
    return GenerationResult(
        content=text, model="fake", tokens_in=1, tokens_out=1, latency_ms=1, estimated_cost=None
    )


def tool_calls_reply(tools: list[dict]) -> GenerationResult:
    """A model turn that calls every evidence tool it was offered (the prebuilt agent's first turn)."""
    calls = [
        ToolCall(
            id=f"call-{i}",
            name=tool["function"]["name"],
            arguments={"query": "recent history, requests and open issues"}
            if tool["function"]["name"] == "search_documents"
            else {},
        )
        for i, tool in enumerate(tools)
    ]
    return GenerationResult(
        content="", model="fake", tokens_in=1, tokens_out=1, latency_ms=1, estimated_cost=None,
        tool_calls=calls,
    )  # fmt: skip


class ScriptedModel:
    """A model that answers by agent role (analyst, reviewer, task_drafter), never by reading the prompt.

    `reviews` are used in order and the last one repeats. `calls` records the roles asked, `prompts` the
    user message each received."""

    def __init__(
        self, analyst: str, reviews: list[str], draft: str = "Send pricing breakdown to Acme"
    ):
        self._analyst, self._reviews, self._draft = analyst, list(reviews), draft
        self.calls: list[str] = []
        self.prompts: dict[str, list[str]] = {}

    async def __call__(self, role, _system_prompt, messages, tools=None):
        self.calls.append(role)
        self.prompts.setdefault(role, []).append(messages[0]["content"])
        if role == "analyst" and tools:
            # the prebuilt agent (AGENT_IMPL=frameworks): ask for the evidence tools once, then answer
            if not any(m["role"] == "tool" for m in messages):
                return tool_calls_reply(tools)
            return reply(self._analyst)
        if role == "analyst":
            return reply(self._analyst)
        if role == "reviewer":
            return reply(self._reviews.pop(0) if len(self._reviews) > 1 else self._reviews[0])
        return reply(json.dumps({"task_note": self._draft}))


def pytest_collection_modifyitems(items):
    """Everything under tests/contract carries the `contract` marker (`pytest -m contract`)."""
    for item in items:
        if "tests/contract/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.contract)


@pytest.fixture(autouse=True)
def retrieval(monkeypatch):
    """Canned document chunks instead of embeddings and the vector store (no key, no Qdrant)."""
    chunks = [
        SimpleNamespace(
            document_title="Onboarding email",
            company_name="Acme Fabrication",
            doc_type="email",
            similarity=0.9,
            content="Asked about onboarding and pricing.",
        )
    ]

    async def retrieve(_query, _company_id=None):
        return chunks

    monkeypatch.setattr("app.mcp.tools.retrieve_relevant_chunks", retrieve)
    return chunks


NO_MODEL_MESSAGE = "No model is configured. Set OPENROUTER_API_KEY in your .env."
NO_EMBEDDINGS_MESSAGE = "GOOGLE_API_KEY is not set."


async def unavailable_model(_role, _system_prompt, _messages, tools=None):
    """A model seam that fails the way the gateway does when no model can be reached."""
    raise LlmUnavailableError(NO_MODEL_MESSAGE)


@pytest.fixture
def embeddings_down(monkeypatch):
    """Document retrieval fails the way it does when the embeddings key is missing."""

    async def retrieve(_query, _company_id=None):
        raise EmbeddingsUnavailableError(NO_EMBEDDINGS_MESSAGE)

    monkeypatch.setattr("app.mcp.tools.retrieve_relevant_chunks", retrieve)


@pytest.fixture
def use_model(monkeypatch):
    """Installs a model for the agent API. Pass a ScriptedModel (or any `llm(role, prompt, messages)`);
    with no argument, a model that recommends, approves and drafts a task note."""

    def install(model=None):
        model = model or ScriptedModel(GOOD_RECOMMENDATION, [APPROVE])
        monkeypatch.setattr("app.routes.agent.make_llm", lambda _model: model)
        return model

    return install


@pytest_asyncio.fixture
async def api():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
        yield client


@pytest_asyncio.fixture(autouse=True)
async def clean_test_tasks():
    """Tasks written by a contract test are removed afterwards, so it can run on a development database."""
    yield
    pool = await get_pool()
    await pool.execute("DELETE FROM tasks WHERE note LIKE $1", f"{TEST_NOTE_PREFIX}%")


async def task_count() -> int:
    pool = await get_pool()
    return int(await pool.fetchval("SELECT COUNT(*) FROM tasks"))
