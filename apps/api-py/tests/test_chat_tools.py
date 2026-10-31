"""The /chat/tools loop with native tool calling: a scripted model, a fake tool server, no network.

What matters here is the loop's rules: bad calls become tool results the model can read, the model
can never decide a task is confirmed, every requested call gets an answer, and the loop is bounded."""

import json
from contextlib import asynccontextmanager

import pytest

from app.llm.types import GenerationResult, ToolCall
from app.mcp.client import ToolSpec
from app.mcp.schemas import TOOL_ARGS
from app.routes import chat


def reply(text="", *calls: ToolCall) -> GenerationResult:
    return GenerationResult(text, "m", 1, 1, 5, 0.0, tool_calls=list(calls))


def call(name: str, arguments: dict, id: str = "c1", error: str | None = None) -> ToolCall:
    return ToolCall(id=id, name=name, arguments=arguments, error=error)


class World:
    """Scripted model replies, recorded model inputs, and recorded tool executions."""

    def __init__(self, replies: list[GenerationResult]):
        self.replies = list(replies)
        self.generations: list[dict] = []
        self.executed: list[tuple[str, dict]] = []
        self.tool_text = json.dumps({"status": "executed", "deals": []})


@pytest.fixture
def world(monkeypatch):
    state = World([])

    async def generate(system_prompt, messages, model=None, *, tools=None, tool_choice="auto"):
        state.generations.append(
            {"messages": [dict(m) for m in messages], "tools": tools, "tool_choice": tool_choice}
        )
        return state.replies.pop(0)

    @asynccontextmanager
    async def session(_backend=None):
        yield object()

    async def specs(_session):
        return [ToolSpec(name, f"does {name}", {}) for name in TOOL_ARGS]

    async def run(_session, name, arguments):
        state.executed.append((name, arguments))
        return state.tool_text

    async def no_audit(_endpoint, _events):
        pass

    monkeypatch.setattr(chat, "generate", generate)
    monkeypatch.setattr(chat, "mcp_session", session)
    monkeypatch.setattr(chat, "list_tool_specs", specs)
    monkeypatch.setattr(chat, "call_tool", run)
    monkeypatch.setattr(chat, "record_events", no_audit)
    return state


async def ask(text: str, history: list[dict] | None = None) -> dict:
    messages = [*(history or []), {"role": "user", "content": text}]
    return await chat.tools_chat(chat.ToolsChatRequest(messages=messages))


@pytest.mark.asyncio
async def test_a_plain_answer_needs_no_tool(world):
    world.replies = [reply("Hello!")]
    out = await ask("hi")
    assert out["message"] == "Hello!" and out["toolsUsed"] == []
    assert {t["function"]["name"] for t in world.generations[0]["tools"]} == set(TOOL_ARGS)


@pytest.mark.asyncio
async def test_a_tool_is_called_and_its_result_goes_back_with_the_call_id(world):
    world.replies = [
        reply("", call("get_open_deals", {"company_name": "Acme"}, id="abc")),
        reply("Acme has no open deals."),
    ]
    out = await ask("Acme deals?")
    assert out["message"] == "Acme has no open deals."
    assert out["toolsUsed"] == [{"tool": "get_open_deals", "arguments": {"company_name": "Acme"}}]
    second = world.generations[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"][0]["id"] == "abc"
    assert json.loads(second[-2]["tool_calls"][0]["function"]["arguments"]) == {
        "company_name": "Acme"
    }
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "abc"
    assert "<untrusted_context>" in second[-1]["content"], "tool output is data, not instructions"


@pytest.mark.asyncio
async def test_the_user_decides_confirmation_not_the_model(world):
    task = {"company_name": "Acme", "note": "call"}
    world.replies = [reply("", call("create_followup_task", task)), reply("Proposed.")]
    await ask("add a follow-up for Acme")
    assert world.executed == [("create_followup_task", {**task, "confirm": False})]

    world.executed.clear()
    world.replies = [reply("", call("create_followup_task", task)), reply("Done.")]
    await ask("yes, go ahead", history=[{"role": "assistant", "content": "Confirm?"}])
    assert world.executed == [("create_followup_task", {**task, "confirm": True})]


@pytest.mark.asyncio
async def test_a_model_trying_to_confirm_itself_is_refused_and_nothing_runs(world):
    bad = call("create_followup_task", {"company_name": "Acme", "note": "x", "confirm": True})
    world.replies = [reply("", bad), reply("Sorry, proposing instead.")]
    out = await ask("add a follow-up for Acme")
    assert world.executed == [] and out["toolsUsed"] == []
    content = world.generations[1]["messages"][-1]["content"]
    assert '"status": "error"' in content and "confirm" in content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        call("drop_database", {}),
        call("get_open_deals", {}),
        call("get_open_deals", {}, error="arguments were not valid JSON"),
    ],
)
async def test_invalid_calls_become_a_tool_error_the_model_can_read(world, bad):
    world.replies = [reply("", bad), reply("I could not look that up.")]
    out = await ask("anything")
    assert world.executed == [] and out["toolsUsed"] == []
    tool_message = world.generations[1]["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == bad.id
    assert '"status": "error"' in tool_message["content"]


@pytest.mark.asyncio
async def test_a_failing_tool_is_reported_to_the_model_not_as_a_503(world, monkeypatch):
    async def boom(*_a):
        raise RuntimeError("database is down")

    monkeypatch.setattr(chat, "call_tool", boom)
    world.replies = [reply("", call("get_open_deals", {"company_name": "Acme"})), reply("Sorry.")]
    out = await ask("Acme deals?")
    assert out["message"] == "Sorry."
    assert "database is down" in world.generations[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_every_requested_call_gets_an_answer_up_to_the_cap(world):
    calls = [call("get_open_deals", {"company_name": f"C{i}"}, id=f"c{i}") for i in range(6)]
    world.replies = [reply("", *calls), reply("ok")]
    await ask("many")
    assert len(world.executed) == chat.MAX_CALLS_PER_REPLY
    messages = world.generations[1]["messages"]
    asked = [c["id"] for c in messages[-(chat.MAX_CALLS_PER_REPLY + 1)]["tool_calls"]]
    answered = [m["tool_call_id"] for m in messages[-chat.MAX_CALLS_PER_REPLY :]]
    assert asked == answered, "a provider rejects an assistant tool call that has no tool message"


@pytest.mark.asyncio
async def test_the_loop_is_bounded_then_a_final_text_answer_is_forced(world):
    looping = [
        reply("", call("get_open_deals", {"company_name": "Acme"}))
        for _ in range(chat.MAX_TOOL_ITERATIONS)
    ]
    world.replies = [*looping, reply("Here is what I found.")]
    out = await ask("loop forever")
    assert out["message"] == "Here is what I found."
    assert len(world.executed) == chat.MAX_TOOL_ITERATIONS
    last = world.generations[-1]
    assert (
        last["tool_choice"] == "none"
        and "maximum number of tool calls" in last["messages"][-1]["content"]
    )


@pytest.mark.asyncio
async def test_a_model_failure_is_a_503(world):
    from fastapi import HTTPException

    world.replies = []  # pop from an empty list raises
    with pytest.raises(HTTPException) as exc:
        await ask("hi")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_an_error_wrapped_by_the_mcp_task_group_is_reported_as_itself(world, monkeypatch):
    """Without this, a missing OpenRouter key showed as "unhandled errors in a TaskGroup"."""
    from fastapi import HTTPException

    from app.llm.gateway import NO_MODEL_MESSAGE, LlmUnavailableError

    @asynccontextmanager
    async def wrapping_session(_backend=None):
        try:
            yield object()
        except LlmUnavailableError as error:
            raise ExceptionGroup("unhandled errors in a TaskGroup", [error]) from error

    async def no_model(*_a, **_k):
        raise LlmUnavailableError(NO_MODEL_MESSAGE)

    monkeypatch.setattr(chat, "mcp_session", wrapping_session)
    monkeypatch.setattr(chat, "generate", no_model)
    with pytest.raises(HTTPException) as exc:
        await ask("hi")
    assert exc.value.status_code == 503 and exc.value.detail == NO_MODEL_MESSAGE


@pytest.mark.asyncio
async def test_the_answer_says_which_mcp_server_was_used(world):
    world.replies = [reply("Hello!")]
    out = await ask("hi")
    assert out["mcpServer"] == "fastmcp"
