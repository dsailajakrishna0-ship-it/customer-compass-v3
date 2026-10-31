"""contracts/mcp-tools.json against the FastMCP server's own tool definitions (offline), and the
checker's own logic. The live check, for either server, is contracts/check_server.py."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "contracts"))

import check_server as check  # noqa: E402

from app.mcp.schemas import TOOL_ARGS  # noqa: E402
from app.mcp.server import server  # noqa: E402

CONTRACT = json.loads((ROOT / "contracts" / "mcp-tools.json").read_text())


@pytest.mark.asyncio
async def test_the_fastmcp_server_matches_the_contract():
    offered = {t.name: t.input_schema for t in await server.list_tools()}
    assert check.compare_tools(offered, CONTRACT["tools"]) == []


def test_the_contract_lists_the_tools_the_model_may_use():
    assert set(CONTRACT["tools"]) == set(TOOL_ARGS)


def test_every_contract_case_names_a_contract_tool_and_never_writes():
    for case in CONTRACT["cases"]:
        assert case["tool"] in CONTRACT["tools"] and case["expect"]
        if case["tool"] == "create_followup_task":
            assert case["arguments"]["confirm"] is False, "a conformance case must not write data"


def test_drift_is_reported():
    schema = {"properties": {"company_name": {"type": "string"}}, "required": ["company_name"]}
    contract = {
        "a": {"required": ["company_name"], "properties": {"company_name": "string"}},
        "b": {"required": [], "properties": {}},
    }
    assert check.compare_tools({"a": schema, "c": schema}, contract) == [
        "offers 'c', which the contract does not list",
        "does not offer 'b'",
    ]
    wrong = {"properties": {"company_name": {"type": "integer"}}, "required": []}
    problems = check.compare_tools({"a": wrong, "b": {}}, contract)
    assert any("arguments are" in p for p in problems) and any("required is" in p for p in problems)


def test_an_optional_argument_may_be_spelled_with_or_without_null():
    contract = {"t": {"required": ["a"], "properties": {"a": "string", "b": "string?"}}}
    plain = {"properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]}
    nullable = {
        "properties": {
            "a": {"type": "string"},
            "b": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["a"],
    }
    assert check.compare_tools({"t": plain}, contract) == []
    assert check.compare_tools({"t": nullable}, contract) == []
    # but a *required* argument must not be nullable
    required_nullable = {
        "properties": {"a": nullable["properties"]["b"], "b": {"type": "string"}},
        "required": ["a"],
    }
    assert check.compare_tools({"t": required_nullable}, contract) != []


def test_nullable_and_plain_types():
    assert check.simple_type({"type": "string"}) == "string"
    assert check.simple_type({"anyOf": [{"type": "string"}, {"type": "null"}]}) == "string?"


def test_expected_values_are_found_by_path_and_mismatches_reported():
    result = {
        "status": "executed",
        "company": {"openDeals": [{"name": "Renewal"}], "wonDealsCount": 1},
    }
    ok = {"id": "x", "expect": {"status": "executed", "company.openDeals.0.name": "Renewal"}}
    assert check.check_case(ok, result) == []
    bad = {
        "id": "x",
        "expect": {"status": "nope", "company.missing": 1, "company.openDeals.5.name": "z"},
    }
    assert [p.split(" is ")[0] for p in check.check_case(bad, result)] == [
        "x: status",
        "x: company.missing",
        "x: company.openDeals.5.name",
    ]
