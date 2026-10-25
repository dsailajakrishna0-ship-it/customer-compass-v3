"""Pure unit tests for Stage 9 (MCP tool calling) building blocks that don't
need a live DB/LLM/MCP subprocess: the confirmation-keyword heuristic and the
chat route's fenced tool_call parsing regex.
"""

import json

from app.mcp.tools import looks_like_confirmation
from app.routes.chat import _TOOL_CALL_PATTERN


def test_looks_like_confirmation_detects_affirmative_words() -> None:
    assert looks_like_confirmation("yes, please do it") is True
    assert looks_like_confirmation("Confirmed.") is True
    assert looks_like_confirmation("go ahead") is True


def test_looks_like_confirmation_rejects_unrelated_text() -> None:
    assert looks_like_confirmation("what are Acme's open deals?") is False
    assert looks_like_confirmation("") is False


def test_tool_call_pattern_extracts_valid_json_block() -> None:
    text = (
        "```tool_call\n"
        '{"tool": "get_open_deals", "arguments": {"company_name": "Acme"}}\n'
        "```"
    )
    match = _TOOL_CALL_PATTERN.search(text)
    assert match is not None
    parsed = json.loads(match.group(1))
    assert parsed == {"tool": "get_open_deals", "arguments": {"company_name": "Acme"}}


def test_tool_call_pattern_does_not_match_plain_text_answer() -> None:
    text = "Acme Fabrication has one open deal: Premium Operations Plan renewal."
    assert _TOOL_CALL_PATTERN.search(text) is None
