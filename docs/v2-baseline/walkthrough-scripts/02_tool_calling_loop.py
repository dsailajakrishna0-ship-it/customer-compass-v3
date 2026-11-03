"""V2's tool-calling loop (POST /chat/tools) with a scripted model: what is sent on each model call.

Part of docs/v2-baseline/code-walkthrough.md. Runs the REAL V2 code (the customer-compass-v2 repository,
tag v2-final) with a scripted stand-in for the model, so the output is the same every time and needs no
Ollama and no keys. It does need a Postgres with the demo data (see docs/v2-baseline/walkthrough-scripts/README.md).

Run from the V2 repository's apps/api-py folder, with V2's own virtualenv:

    cd ../customer-compass-v2/apps/api-py
    DATABASE_URL=postgresql://customer_compass:customer_compass_dev@localhost:55432/customer_compass \
      PYTHONPATH=. ./.venv/bin/python <path to this repo>/docs/v2-baseline/walkthrough-scripts/02_tool_calling_loop.py
"""

import asyncio
import json
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://customer_compass:customer_compass_dev@localhost:55432/customer_compass",
)
from app.llm.types import GenerationResult
from app.routes import chat

replies = [
    '```tool_call\n{"tool": "get_open_deals", "arguments": {"company_name": "Acme"}}\n```',
    "Acme Fabrication has one open deal: Premium Operations Plan renewal ($48,000.00, expected close 2026-10-15).",
]
calls = []


async def fake_generate(system_prompt, messages, provider=None, model=None):
    calls.append((system_prompt, [dict(m) for m in messages]))
    return GenerationResult(
        content=replies[len(calls) - 1],
        provider="ollama",
        model="fake",
        tokens_in=1,
        tokens_out=1,
        latency_ms=1,
        estimated_cost=0.0,
    )


chat.generate = fake_generate


async def main():
    body = chat.ChatRequest(
        messages=[{"role": "user", "content": "What are Acme Fabrication's open deals?"}]
    )
    out = await chat.tools_chat(body)
    print(
        "##### SYSTEM PROMPT sent on EVERY model call (the {tool_descriptions} part is filled from the live MCP tool list)\n"
    )
    print(calls[0][0])
    for i, (_sp, msgs) in enumerate(calls, 1):
        print(f"\n##### MODEL CALL {i}: messages sent ({len(msgs)})")
        for m in msgs:
            print(f"[{m['role']}] {m['content']}")
    print("\n##### RESPONSE of POST /chat/tools")
    print(json.dumps({k: out[k] for k in ("message", "toolsUsed", "provider")}, indent=2))


asyncio.run(main())
