"""Both observed approaches against a scripted model: the same question, the same signals, two
ways of capturing them (LangChain callbacks, LangGraph stream updates). No key, no network.
See docs/adr/0040."""

import json

import pytest
from fastapi.testclient import TestClient
from lab_common.chat import Message, UnavailableError
from lab_common.server import create_app
from lab_common.telemetry import Telemetry
from lab_common.testing import ai, scripted, tool_call
from observed_langchain import ObservationHandler, ObservedLangChainToolChat
from observed_langgraph import ObservedLangGraphToolChat

OBSERVED = [ObservedLangChainToolChat, ObservedLangGraphToolChat]
ASK = [Message("user", "What deals does Acme Fabrication have?")]


def observed(approach, crm_tools, *replies):
    telemetry = Telemetry()
    chat = approach(crm_tools, model=scripted(*replies))
    chat.observe_with(telemetry)
    return chat, telemetry


def only_trace(telemetry):
    traces = telemetry.recent_json()["traces"]
    assert len(traces) == 1
    return {span["name"]: span for span in traces[0]["spans"]}, traces[0]["spans"]


def counter(telemetry, name):
    return {
        tuple(sorted(p["attributes"].items())): p["value"]
        for m in telemetry.metrics()
        if m["name"] == name
        for p in m["points"]
    }


@pytest.mark.parametrize("approach", OBSERVED)
def test_one_trace_per_question_with_a_span_per_model_call_and_per_tool(approach, crm_tools):
    chat, telemetry = observed(
        approach,
        crm_tools,
        ai("", [tool_call("get_open_deals", {"company_name": "Acme"})]),
        ai("Acme has one open deal."),
    )
    result = chat.answer(ASK, None)
    assert result.message == "Acme has one open deal."
    by_name, spans = only_trace(telemetry)
    assert sorted(s["name"] for s in spans) == [
        "chat.request",
        "llm.generate",
        "llm.generate",
        "tool.get_open_deals",
    ]
    root = by_name["chat.request"]["attributes"]
    assert root["cc.approach"] == chat.approach and root["cc.status"] == "ok"
    assert (root["cc.model_calls"], root["cc.tool_calls"]) == (2, 1)
    assert by_name["tool.get_open_deals"]["attributes"]["cc.outcome"] == "ran"
    llm = [s["attributes"] for s in spans if s["name"] == "llm.generate"]
    assert all(
        a["gen_ai.usage.input_tokens"] == 11 and a["gen_ai.usage.output_tokens"] == 7 for a in llm
    )
    assert all(a["gen_ai.request.model"] == "meta-llama/llama-3.1-8b-instruct" for a in llm)


@pytest.mark.parametrize("approach", OBSERVED)
def test_the_metrics_count_requests_model_calls_tools_and_tokens(approach, crm_tools):
    chat, telemetry = observed(
        approach,
        crm_tools,
        ai("", [tool_call("get_open_deals", {"company_name": "Acme"})]),
        ai("done"),
    )
    chat.answer(ASK, "google/gemini-x")
    assert sum(counter(telemetry, "cc.chat.requests").values()) == 1
    assert sum(counter(telemetry, "cc.chat.model_calls").values()) == 2
    assert sum(counter(telemetry, "cc.chat.tool_calls").values()) == 1
    tokens = counter(telemetry, "gen_ai.client.token.usage")
    assert {k: v for k, v in tokens.items()} == {
        (("cc.approach", chat.approach), ("gen_ai.token.type", "input")): 22,
        (("cc.approach", chat.approach), ("gen_ai.token.type", "output")): 14,
    }
    assert telemetry.recent_json()["traces"][0]["spans"][0]["attributes"].get(
        "gen_ai.request.model"
    ) in {"google/gemini-x", "meta-llama/llama-3.1-8b-instruct"}


@pytest.mark.parametrize("approach", OBSERVED)
def test_nothing_a_user_or_a_model_wrote_is_ever_recorded(approach, crm_tools):
    chat, telemetry = observed(
        approach,
        crm_tools,
        ai("", [tool_call("get_open_deals", {"company_name": "Acme Fabrication"})]),
        ai("The secret answer is forty-two."),
    )
    chat.answer(ASK, None)
    recorded = json.dumps(telemetry.recent_json())
    for text in (
        "What deals",
        "Acme",
        "Fabrication",
        "secret answer",
        "untrusted_context",
        "Renewal",
    ):
        assert text not in recorded


@pytest.mark.parametrize("approach", OBSERVED)
@pytest.mark.parametrize(
    "arguments", [{}, {"company_name": 5}], ids=["missing argument", "wrong type"]
)
def test_bad_arguments_are_an_invalid_arguments_tool_span(approach, crm_tools, arguments):
    chat, telemetry = observed(
        approach, crm_tools, ai("", [tool_call("get_open_deals", arguments)]), ai("Sorry.")
    )
    chat.answer(ASK, None)
    by_name, _ = only_trace(telemetry)
    assert by_name["tool.get_open_deals"]["attributes"]["cc.outcome"] == "invalid_arguments"


@pytest.mark.parametrize("approach", OBSERVED)
def test_a_tool_that_does_not_exist_is_recorded_as_unknown_never_by_the_name_the_model_made_up(
    approach, crm_tools
):
    chat, telemetry = observed(
        approach,
        crm_tools,
        ai("", [tool_call("delete_all", {"company_name": "Acme"})]),
        ai("Sorry."),
    )
    chat.answer(ASK, None)
    by_name, _ = only_trace(telemetry)
    assert by_name["tool.unknown"]["attributes"]["cc.outcome"] == "invalid_call"
    assert "delete_all" not in json.dumps(telemetry.recent_json())


@pytest.mark.parametrize("approach", OBSERVED)
def test_two_tools_asked_in_one_message_give_two_tool_spans(approach, crm_tools):
    calls = [
        tool_call("get_open_deals", {"company_name": "Acme"}, "a"),
        tool_call("get_company_summary", {"company_name": "Acme"}, "b"),
    ]
    chat, telemetry = observed(approach, crm_tools, ai("", calls), ai("done"))
    chat.answer(ASK, None)
    _, spans = only_trace(telemetry)
    assert sorted(s["name"] for s in spans if s["name"].startswith("tool.")) == [
        "tool.get_company_summary",
        "tool.get_open_deals",
    ]


def test_a_failing_model_call_is_a_failed_request_and_only_langchain_reports_the_failed_model_call(
    crm_tools,
):
    langchain, t1 = observed(
        ObservedLangChainToolChat, crm_tools
    )  # an empty script: the model raises
    graph, t2 = observed(ObservedLangGraphToolChat, crm_tools)
    for chat in (langchain, graph):
        with pytest.raises(UnavailableError):
            chat.answer(ASK, None)
    names1 = {s["name"]: s["attributes"] for s in only_trace(t1)[1]}
    names2 = {s["name"]: s["attributes"] for s in only_trace(t2)[1]}
    assert (
        names1["chat.request"]["cc.status"] == "error"
        and names1["chat.request"]["cc.failure"] == "model_unavailable"
    )
    assert names2["chat.request"]["cc.status"] == "error"
    assert names1["llm.generate"]["cc.outcome"] == "error"  # the callback's on_llm_error
    assert "llm.generate" not in names2  # a stream of updates has no event for a node that failed


@pytest.mark.parametrize("approach", OBSERVED)
def test_observation_off_changes_nothing_in_the_answer(approach, crm_tools):
    plain = approach(
        crm_tools,
        model=scripted(ai("", [tool_call("get_open_deals", {"company_name": "Acme"})]), ai("done")),
    )
    assert (
        plain.answer(ASK, None).message == "done"
    )  # no observer set: nothing recorded, nothing breaks


def test_the_recent_route_shows_the_traces_and_is_404_with_a_hint_when_observation_is_off(
    crm_tools,
):
    chat, telemetry = observed(ObservedLangChainToolChat, crm_tools, ai("hi"))
    chat.answer(ASK, None)
    on = TestClient(create_app(chat, telemetry)).get("/api/v1/observability/recent")
    assert on.status_code == 200 and on.json()["enabled"] is True and on.json()["traces"]
    off = TestClient(create_app(chat)).get("/api/v1/observability/recent")
    assert off.status_code == 404 and "TELEMETRY_ENABLED=true" in off.json()["detail"]


def test_measured_langchain_callbacks_never_see_a_tool_that_does_not_exist(crm_tools):
    from langchain.agents import create_agent
    from tool_calling_with_langchain import build_tools

    model = scripted(ai("", [tool_call("delete_all", {"company_name": "Acme"})]), ai("Sorry."))
    agent = create_agent(model, build_tools(crm_tools))

    class Recorder:
        def __init__(self):
            self.request = type(
                "R", (), {"model_call": lambda *a, **k: None, "tool_call": lambda *a, **k: None}
            )()

    handler = ObservationHandler(Recorder().request, "m")
    agent.invoke({"messages": [("user", "q")]}, config={"callbacks": [handler]})
    assert handler.tools_seen == []


def test_measured_the_langgraph_stream_yields_one_event_per_node_that_ran(crm_tools):
    from tool_calling_with_langgraph import build_graph, build_tools

    model = scripted(ai("", [tool_call("get_open_deals", {"company_name": "Acme"})]), ai("done"))
    graph = build_graph(model, build_tools(crm_tools))
    events = [
        next(iter(update))
        for update in graph.stream(
            {"messages": [("user", "q")], "rounds": 0}, stream_mode="updates"
        )
    ]
    assert events == ["model", "tools", "count_round", "model"]
