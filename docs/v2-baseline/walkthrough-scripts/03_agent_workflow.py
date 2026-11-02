"""V2's agent workflow with scripted agents: what each agent receives, and the trace.

Part of docs/v2-baseline/code-walkthrough.md. Runs the REAL V2 code (the customer-compass-v2 repository,
tag v2-final) with a scripted stand-in for the model, so the output is the same every time and needs no
Ollama and no keys. It does need a Postgres with the demo data (see docs/v2-baseline/walkthrough-scripts/README.md).

Run from the V2 repository's apps/api-py folder, with V2's own virtualenv:

    cd ../customer-compass-v2/apps/api-py
    DATABASE_URL=postgresql://customer_compass:customer_compass_dev@localhost:55432/customer_compass \
      PYTHONPATH=. ./.venv/bin/python <path to this repo>/docs/v2-baseline/walkthrough-scripts/03_agent_workflow.py
"""

import asyncio
import json
import os
from types import SimpleNamespace

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://customer_compass:customer_compass_dev@localhost:55432/customer_compass",
)
from app.agent import workflow
from app.llm.types import GenerationResult
from app.mcp import tools


async def retrieve(q, cid=None):
    return [
        SimpleNamespace(
            document_title="Onboarding email",
            company_name="Acme Fabrication",
            doc_type="email",
            similarity=0.9,
            content="Asked about onboarding and pricing.",
        )
    ]


tools.retrieve_relevant_chunks = retrieve

scripts = {
    "analyst": [
        '{"action": "Call Acme about renewal", "rationale": "Renewal is near.", "evidence": []}',
        '{"action": "Send Acme the renewal pricing before 2026-10-15", "rationale": "A $48,000 renewal closes 2026-10-15 and they asked about pricing.", "evidence": ["E2", "E4"]}',
    ],
    "reviewer": ['{"verdict": "approve", "reasons": []}', '{"verdict": "approve", "reasons": []}'],
    "drafter": ['{"task_note": "Send Acme renewal pricing before Oct 15"}'],
}
n = {"analyst": 0, "reviewer": 0, "drafter": 0}
prompts = []


async def llm(system_prompt, messages):
    role = (
        "analyst"
        if system_prompt.startswith("You are the Analyst")
        else "reviewer"
        if system_prompt.startswith("You are the Reviewer")
        else "drafter"
    )
    prompts.append((role, messages[0]["content"]))
    text = scripts[role][min(n[role], len(scripts[role]) - 1)]
    n[role] += 1
    return GenerationResult(
        content=text,
        provider="ollama",
        model="fake",
        tokens_in=1,
        tokens_out=1,
        latency_ms=1,
        estimated_cost=0.0,
    )


async def main():
    out = await workflow.run_account_review(
        "Analyze Acme Fabrication and recommend a next action", llm
    )
    for i, (role, p) in enumerate(prompts, 1):
        print(f"##### AGENT CALL {i}: {role} receives this user message\n{p}\n")
    print("##### TRACE")
    for s in out["trace"]:
        print(f"{s['index']:>2} {s['kind']:<5} {s['name']:<28} -> {s['output_summary'][:90]}")
    print("\n##### RESPONSE KEYS:", list(out.keys()))
    print("review:", json.dumps(out["review"]))
    print("proposedTask:", json.dumps(out["proposedTask"]))


asyncio.run(main())
