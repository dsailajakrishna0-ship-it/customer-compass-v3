"""Both tool-calling approaches against a scripted model: no key, no network.

The first group is the behaviour they share; the second group is where they differ, which is what
the comparison is about (see docs/adr/0037).
"""

import pytest
from lab_common.chat import Message, UnavailableError
from lab_common.crm import MAX_ROUNDS, SUMMARY_DESCRIPTION, SYSTEM_PROMPT
from lab_common.testing import ai, scripted, tool_call
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from tool_calling_with_langchain import LangChainToolChat
from tool_calling_with_langchain import build_tools as langchain_tools
from tool_calling_with_langgraph import LangGraphToolChat

APPROACHES = [LangChainToolChat, LangGraphToolChat]
ASK = [Message("user", "What deals does Acme have?")]


def make(approach, crm_tools, *replies):
    model = scripted(*replies)
    return approach(crm_tools, model=model), model


@pytest.mark.parametrize("approach", APPROACHES)
def test_the_model_asks_for_a_tool_the_tool_runs_and_the_model_answers(approach, crm_tools):
    chat, model = make(
        approach,
        crm_tools,
        ai("", [tool_call("get_open_deals", {"company_name": "Acme"})]),
        ai("Acme has one open deal."),
    )
    result = chat.answer(ASK, None)
    assert result.message == "Acme has one open deal."
    assert [(u.tool, u.arguments) for u in result.tools_used] == [
        ("get_open_deals", {"company_name": "Acme"})
    ]
    assert result.usage.model == "meta-llama/llama-3.1-8b-instruct"
    assert (result.usage.tokens_in, result.usage.tokens_out) == (11, 7)
    assert (
        model.tools_bound == ["get_company_summary", "get_open_deals"]
        or approach is LangChainToolChat
    )


@pytest.mark.parametrize("approach", APPROACHES)
def test_the_system_prompt_goes_first_and_the_conversation_follows(approach, crm_tools):
    chat, model = make(approach, crm_tools, ai("hello"))
    chat.answer(
        [Message("user", "hi"), Message("assistant", "hello"), Message("user", "and now?")], None
    )
    sent = model.seen[0]
    assert isinstance(sent[0], SystemMessage) and sent[0].content == SYSTEM_PROMPT
    assert [type(m).__name__ for m in sent[1:]] == ["HumanMessage", "AIMessage", "HumanMessage"]


@pytest.mark.parametrize("approach", APPROACHES)
def test_a_tool_result_reaches_the_model_wrapped_as_data(approach, crm_tools):
    chat, model = make(
        approach,
        crm_tools,
        ai("", [tool_call("get_company_summary", {"company_name": "Acme"})]),
        ai("done"),
    )
    chat.answer(ASK, None)
    tool_message = next(m for m in model.seen[1] if isinstance(m, ToolMessage))
    assert tool_message.content.startswith("<untrusted_context>")
    assert tool_message.content.endswith("</untrusted_context>")
    assert "Manufacturing" in tool_message.content


@pytest.mark.parametrize("approach", APPROACHES)
@pytest.mark.parametrize(
    ("name", "arguments", "text"),
    [
        ("delete_all", {"company_name": "Acme"}, "not a valid tool"),
        ("get_open_deals", {}, "company_name"),
        ("get_open_deals", {"company_name": 5, "x": 1}, "company_name"),
    ],
    ids=["unknown tool", "missing argument", "wrong type and extra argument"],
)
def test_a_bad_call_is_answered_with_an_error_text_the_model_can_read_never_an_exception(
    approach, crm_tools, name, arguments, text
):
    chat, model = make(approach, crm_tools, ai("", [tool_call(name, arguments)]), ai("Sorry."))
    assert chat.answer(ASK, None).message == "Sorry."
    error = next(m for m in model.seen[1] if isinstance(m, ToolMessage))
    assert text in error.content
    assert not error.content.startswith(
        "<untrusted_context>"
    )  # the library's own text, not our wrapper


@pytest.mark.parametrize("approach", APPROACHES)
def test_the_clients_model_replaces_the_default_in_the_usage(approach, crm_tools):
    chat, _ = make(approach, crm_tools, ai("hi"))
    assert chat.answer(ASK, "google/gemini-x").usage.model == "google/gemini-x"


@pytest.mark.parametrize("approach", APPROACHES)
def test_no_key_means_no_call(approach, crm_tools):
    with pytest.raises(UnavailableError, match="OPENROUTER_API_KEY"):
        approach(crm_tools).answer(ASK, None)


@pytest.mark.parametrize("approach", APPROACHES)
def test_a_failing_model_call_is_reported_by_kind_never_by_the_services_text(approach, crm_tools):
    chat, _ = make(approach, crm_tools)  # an empty script: the scripted model raises
    with pytest.raises(UnavailableError) as info:
        chat.answer(ASK, None)
    assert "more often than the test scripted" not in str(info.value)
    assert "AssertionError" in str(info.value)


def keeps_asking(n):
    return [
        ai("", [tool_call("get_open_deals", {"company_name": "Acme"}, f"c{i}")]) for i in range(n)
    ]


def test_langgraph_forces_a_last_plain_answer_after_the_round_limit(crm_tools):
    chat, model = make(
        LangGraphToolChat, crm_tools, *keeps_asking(MAX_ROUNDS + 1), ai("final plain answer")
    )
    result = chat.answer(ASK, None)
    assert result.message == "final plain answer"
    assert len(result.tools_used) == MAX_ROUNDS  # the fifth ask was never run
    last_call = model.seen[-1]
    assert (
        isinstance(last_call[-1], HumanMessage)
        and "maximum number of tool calls" in last_call[-1].content
    )


def test_langchain_ends_with_a_canned_message_at_the_round_limit_not_a_model_answer(crm_tools):
    chat, model = make(
        LangChainToolChat, crm_tools, *keeps_asking(MAX_ROUNDS + 1), ai("never reached")
    )
    result = chat.answer(ASK, None)
    assert "Model call limits exceeded" in result.message  # the library's own text
    assert len(model.seen) == MAX_ROUNDS + 1


def test_langchain_writes_the_tool_schema_from_the_signature_and_the_docstring(crm_tools):
    tool = langchain_tools(crm_tools)[0]
    assert tool.description == SUMMARY_DESCRIPTION
    schema = tool.tool_call_schema.model_json_schema()
    assert schema["required"] == ["company_name"]
    assert schema["properties"]["company_name"]["type"] == "string"
    assert (
        schema["properties"]["company_name"]["description"]
        == "The company's name, as the user wrote it."
    )


def test_langgraph_binds_both_tools_to_the_model_itself(crm_tools):
    chat, model = make(LangGraphToolChat, crm_tools, ai("hi"))
    chat.answer(ASK, None)
    assert model.tools_bound == ["get_company_summary", "get_open_deals"]
