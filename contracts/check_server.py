#!/usr/bin/env python3
"""Checks a running MCP tool server against contracts/mcp-tools.json.

    uv run --project apps/api-py python contracts/check_server.py http://localhost:8002/mcp

1. The server offers exactly the contract's tools, with the contract's argument names, types and
   required fields.
2. Every case in the contract, called with its arguments, returns the expected values.

Needs the demo data (migration 0002). The `search_documents` tool is checked for its schema only: a
call needs the embeddings API and a populated vector store. Cases never write data.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

CONTRACT = Path(__file__).resolve().parent / "mcp-tools.json"


def simple_type(schema: dict) -> str:
    """'string', 'boolean', ... or 'string?' for a nullable one, from a JSON Schema property."""
    if "anyOf" in schema:
        kinds = [part.get("type") for part in schema["anyOf"]]
        real = [k for k in kinds if k != "null"]
        return f"{real[0]}?" if "null" in kinds and len(real) == 1 else "|".join(map(str, kinds))
    return str(schema.get("type"))


def strip_optional(kind: str, is_required: bool) -> str:
    """'string?' and 'string' are the same for an argument that is not required."""
    return kind if is_required else kind.removesuffix("?")


def compare_tools(offered: dict[str, dict], contract: dict[str, dict]) -> list[str]:
    """Differences between the server's tools ({name: input schema}) and the contract's."""
    problems = []
    for name in sorted(set(offered) - set(contract)):
        problems.append(f"offers {name!r}, which the contract does not list")
    for name, want in contract.items():
        if name not in offered:
            problems.append(f"does not offer {name!r}")
            continue
        schema = offered[name]
        required = set(want["required"])
        # An optional argument may be spelled "string" or "string or null" by different frameworks.
        got_props = {
            k: strip_optional(simple_type(v), k in required)
            for k, v in schema.get("properties", {}).items()
        }
        want_props = {k: strip_optional(v, k in required) for k, v in want["properties"].items()}
        if got_props != want_props:
            problems.append(
                f"{name}: arguments are {got_props}, contract says {want['properties']}"
            )
        if sorted(schema.get("required", [])) != sorted(want["required"]):
            problems.append(
                f"{name}: required is {schema.get('required', [])}, contract says {want['required']}"
            )
    return problems


def lookup(value: object, path: str) -> object:
    """Follows a dotted path ('company.openDeals.0.name') through dicts and lists."""
    for part in path.split("."):
        if isinstance(value, list):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(path)
    return value


def check_case(case: dict, result: dict) -> list[str]:
    problems = []
    for path, want in case["expect"].items():
        try:
            got = lookup(result, path)
        except (KeyError, IndexError, ValueError):
            problems.append(f"{case['id']}: {path} is missing (wanted {want!r})")
            continue
        if got != want:
            problems.append(f"{case['id']}: {path} is {got!r}, wanted {want!r}")
    return problems


async def run(url: str) -> list[str]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    contract = json.loads(CONTRACT.read_text())
    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            problems = compare_tools({t.name: t.input_schema for t in tools}, contract["tools"])
            for case in contract["cases"]:
                reply = await session.call_tool(case["tool"], case["arguments"])
                text = "\n".join(b.text for b in reply.content if hasattr(b, "text"))
                try:
                    problems += check_case(case, json.loads(text))
                except json.JSONDecodeError:
                    problems.append(f"{case['id']}: the reply is not JSON: {text[:80]!r}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    problems = asyncio.run(run(argv[1]))
    for problem in problems:
        print("FAIL", problem)
    cases = len(json.loads(CONTRACT.read_text())["cases"])
    print(f"{argv[1]}: {'OK' if not problems else f'{len(problems)} problem(s)'} ({cases} cases)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
