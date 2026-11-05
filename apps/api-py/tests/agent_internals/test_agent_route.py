import pytest
from fastapi import HTTPException

from app.routes import agent as agent_route


@pytest.fixture(autouse=True)
def no_paused_run(monkeypatch):
    """By default there is no paused run to resume, so /confirm takes its direct path."""

    async def none(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_route, "resume_run", none)


@pytest.mark.asyncio
async def test_a_paused_run_is_resumed_instead_of_writing_directly(monkeypatch):
    async def resumed(company_name, note, confirm):
        return {"status": "confirmed", "task": {"id": 7}}

    async def boom(*_args, **_kwargs):
        raise AssertionError("the resumed run does the write, not the route")

    monkeypatch.setattr(agent_route, "resume_run", resumed)
    monkeypatch.setattr(agent_route, "create_followup_task_tool", boom)
    result = await agent_route.confirm(
        agent_route.ConfirmRequest(companyName="Acme", note="Call them", confirm=True)
    )
    assert result["task"]["id"] == 7


@pytest.mark.asyncio
async def test_simple_question_bypasses_the_agent(monkeypatch):
    async def boom(*_args, **_kwargs):
        raise AssertionError("workflow must not run for simple questions")

    monkeypatch.setattr(agent_route, "run_account_review", boom)
    result = await agent_route.recommend(
        agent_route.RecommendRequest(message="What is Acme's industry?")
    )
    assert result["route"] == "direct"


@pytest.mark.asyncio
async def test_declining_creates_no_task(monkeypatch):
    async def boom(*_args, **_kwargs):
        raise AssertionError("no task may be created when the user declines")

    monkeypatch.setattr(agent_route, "create_followup_task_tool", boom)
    result = await agent_route.confirm(
        agent_route.ConfirmRequest(companyName="Acme", note="Call them", confirm=False)
    )
    assert result["status"] == "declined"


@pytest.mark.asyncio
async def test_confirming_creates_the_task_with_confirm_flag(monkeypatch):
    captured = {}

    async def fake_tool(company_name, note, confirm=False):
        captured.update(company_name=company_name, note=note, confirm=confirm)
        return {"status": "confirmed", "task": {"id": 1}}

    monkeypatch.setattr(agent_route, "create_followup_task_tool", fake_tool)
    result = await agent_route.confirm(
        agent_route.ConfirmRequest(companyName="Acme", note="Call them", confirm=True)
    )
    assert result["status"] == "confirmed"
    assert captured == {"company_name": "Acme", "note": "Call them", "confirm": True}


@pytest.mark.asyncio
async def test_confirm_unknown_company_is_404(monkeypatch):
    async def fake_tool(*_args, **_kwargs):
        return {"status": "not_found", "message": "No company"}

    monkeypatch.setattr(agent_route, "create_followup_task_tool", fake_tool)
    with pytest.raises(HTTPException) as exc:
        await agent_route.confirm(
            agent_route.ConfirmRequest(companyName="Nope", note="x", confirm=True)
        )
    assert exc.value.status_code == 404
