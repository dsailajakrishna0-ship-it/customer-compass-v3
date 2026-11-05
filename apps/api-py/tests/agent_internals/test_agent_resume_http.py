"""Stage 3.2b over HTTP: /agent/recommend pauses the run, /agent/confirm resumes it (real Postgres).

Uses the contract tests' fakes (model and retrieval) but lives here because it looks inside: it checks
that the task was written by the resumed run, which an outside caller cannot see."""

import pytest

from app.agent import workflow
from app.agent.checkpoint import get_checkpointer, thread_id
from tests.contract.conftest import (  # noqa: F401  (pytest fixtures)
    TEST_NOTE_PREFIX,
    ScriptedModel,
    api,
    clean_test_tasks,
    retrieval,
    task_count,
    use_model,
)

ASK = "Analyze Acme Fabrication and recommend a next action"


@pytest.mark.asyncio
async def test_confirm_resumes_the_run_that_recommend_paused(api, use_model):  # noqa: F811
    from tests.contract.conftest import APPROVE, GOOD_RECOMMENDATION

    use_model(
        ScriptedModel(GOOD_RECOMMENDATION, [APPROVE], draft=f"{TEST_NOTE_PREFIX} send pricing")
    )
    proposed = (await api.post("/api/v1/agent/recommend", json={"message": ASK})).json()[
        "proposedTask"
    ]

    saver = await get_checkpointer()
    config = {"configurable": {"thread_id": thread_id(proposed["companyName"], proposed["note"])}}
    paused = await workflow._approval_graph(saver).aget_state(config)
    assert paused.next == ("human_approval",), "recommend must leave the run paused in Postgres"

    before = await task_count()
    reply = await api.post("/api/v1/agent/confirm", json={**proposed, "confirm": True})
    assert reply.status_code == 200 and reply.json()["status"] == "confirmed"
    assert await task_count() == before + 1

    finished = await workflow._approval_graph(saver).aget_state(config)
    assert finished.next == () and finished.values["result"]["status"] == "confirmed"
