"""Pure unit tests for Stage 9 (MCP tool calling) building blocks that don't
need a live DB/LLM/MCP subprocess: the confirmation-keyword heuristic and the
chat route's tool-call loop is tested in test_chat_tools.py.
"""

from app.mcp.tools import looks_like_confirmation


def test_looks_like_confirmation_detects_affirmative_words() -> None:
    assert looks_like_confirmation("yes, please do it") is True
    assert looks_like_confirmation("Confirmed.") is True
    assert looks_like_confirmation("go ahead") is True


def test_looks_like_confirmation_rejects_unrelated_text() -> None:
    assert looks_like_confirmation("what are Acme's open deals?") is False
    assert looks_like_confirmation("") is False
