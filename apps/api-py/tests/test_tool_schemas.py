"""The model-facing tool schemas: what is offered, what is accepted, what is refused."""

import pytest

from app.mcp.client import ToolSpec
from app.mcp.schemas import TOOL_ARGS, tool_definitions, validate_arguments
from app.mcp.server import server


@pytest.mark.asyncio
async def test_every_tool_the_server_offers_has_a_schema_and_nothing_else_does():
    served = {t.name for t in await server.list_tools()}
    assert served == set(TOOL_ARGS), "add a Pydantic model in app/mcp/schemas.py for every new tool"


def specs() -> list[ToolSpec]:
    return [ToolSpec(n, f"does {n}", {}) for n in [*TOOL_ARGS, "debug_dump_everything"]]


def test_definitions_use_our_schemas_and_skip_tools_without_one():
    definitions = {d["function"]["name"]: d["function"] for d in tool_definitions(specs())}
    assert set(definitions) == set(TOOL_ARGS), "a tool with no model is never offered"
    task = definitions["create_followup_task"]
    assert task["description"] == "does create_followup_task"
    assert set(task["parameters"]["properties"]) == {"company_name", "note"}
    assert task["parameters"]["required"] == ["company_name", "note"]
    assert "title" not in task["parameters"]


def test_the_model_is_never_offered_a_confirm_argument():
    for definition in tool_definitions(specs()):
        assert "confirm" not in definition["function"]["parameters"]["properties"]


def test_valid_arguments_are_cleaned_and_optional_ones_dropped():
    assert validate_arguments("search_documents", {"query": "pricing", "company_name": None}) == {
        "query": "pricing"
    }


@pytest.mark.parametrize(
    "name, arguments, message",
    [
        ("create_followup_task", {"company_name": "Acme", "note": "x", "confirm": True}, "confirm"),
        ("get_open_deals", {}, "company_name"),
        ("get_open_deals", {"company_name": ""}, "company_name"),
        ("get_open_deals", {"company_name": 7}, "company_name"),
        ("create_followup_task", {"company_name": "A", "note": "n" * 501}, "note"),
        ("drop_database", {}, "no tool called"),
    ],
)
def test_bad_arguments_are_refused_with_a_message_the_model_can_act_on(name, arguments, message):
    with pytest.raises(ValueError, match=message):
        validate_arguments(name, arguments)
