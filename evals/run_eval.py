"""V3 evaluation baseline runner.

Run with the API project's environment (see the `eval` recipes in the justfile):

    uv run --project apps/api-py python evals/run_eval.py --out evals/baseline/v2.json
    uv run --project apps/api-py python evals/run_eval.py --check evals/baseline/v2.json

Suites:
  adversarial  rule-based guard against evals/adversarial-prompts.json (offline, deterministic)
  retrieval    recall@k and MRR of Qdrant retrieval against evals/golden/retrieval.json
               (needs the stack up, documents ingested, and GOOGLE_API_KEY for query embeddings)
  tools        which MCP tool the model picks, evals/golden/tool_calls.json (needs the API and a model)
  agent        routing and outcome of the Stage 10 workflow, evals/golden/agent.json (needs the API and a model)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS))  # metrics.py
sys.path.insert(0, str(EVALS.parent / "apps" / "api-py"))  # the app package
import metrics  # noqa: E402

SUITES = ("adversarial", "retrieval", "tools", "agent")
# Allowed absolute difference per suite when reproducing a baseline. Retrieval is stable;
# tool and agent results depend on a sampled model, so they get a wider band.
TOLERANCES = {"adversarial": 0.0, "retrieval": 0.02, "tools": 0.2, "agent": 0.2}
# Metrics that describe cost or speed are reported but never compared
INFORMATIONAL = {"mean_latency_s", "cases", "mean_steps"}
RETRIEVAL_FETCH = 10  # chunks fetched per question; documents are deduped from these


def _load(name: str) -> list[dict]:
    return json.loads((EVALS / name).read_text())


# ---------------------------------------------------------------- adversarial


def run_adversarial() -> dict:
    from app.guardrails.prompt_guard import scan_and_neutralize

    cases = _load("adversarial-prompts.json")
    results = []
    for case in cases:
        flagged = scan_and_neutralize(case["prompt"]).flagged
        results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "is_attack": case["is_attack"],
                "flagged": flagged,
            }
        )
    attacks = [r for r in results if r["is_attack"]]
    benign = [r for r in results if not r["is_attack"]]
    return {
        "metrics": {
            "cases": len(results),
            "attack_detection_rate": metrics.rate([r["flagged"] for r in attacks]),
            "false_positive_rate": metrics.rate([r["flagged"] for r in benign]),
        },
        "cases": results,
    }


# ------------------------------------------------------------------ retrieval


async def run_retrieval() -> dict:
    from app.db import get_pool
    from app.rag.retrieve import get_point_count, retrieve_relevant_chunks

    if await get_point_count() == 0:
        raise SystemExit("Qdrant has no documents: start the stack and run `just seed` first.")
    pool = await get_pool()
    results = []
    for case in _load("golden/retrieval.json"):
        company_id = None
        if case["company"]:
            company_id = await pool.fetchval(
                "SELECT id FROM companies WHERE name = $1", case["company"]
            )
        chunks = await retrieve_relevant_chunks(case["question"], company_id, RETRIEVAL_FETCH)
        ranked = metrics.dedupe_keep_order([Path(c.source_path).name for c in chunks])
        relevant = set(case["relevant"])
        row = {"id": case["id"], "ranked": ranked, "relevant": sorted(relevant)}
        if relevant:
            row.update(
                recall_at_1=metrics.recall_at_k(ranked, relevant, 1),
                recall_at_3=metrics.recall_at_k(ranked, relevant, 3),
                recall_at_5=metrics.recall_at_k(ranked, relevant, 5),
                reciprocal_rank=metrics.reciprocal_rank(ranked, relevant),
            )
        else:
            row["declined"] = not ranked
        results.append(row)
    answerable = [r for r in results if "recall_at_1" in r]
    unanswerable = [r for r in results if "declined" in r]
    return {
        "metrics": {
            "cases": len(results),
            "recall_at_1": metrics.mean([r["recall_at_1"] for r in answerable]),
            "recall_at_3": metrics.mean([r["recall_at_3"] for r in answerable]),
            "recall_at_5": metrics.mean([r["recall_at_5"] for r in answerable]),
            "mrr": metrics.mean([r["reciprocal_rank"] for r in answerable]),
            "unanswerable_decline_rate": metrics.rate([r["declined"] for r in unanswerable]),
        },
        "cases": results,
    }


# ------------------------------------------------------------ tools and agent


async def _task_count() -> int:
    from app.db import get_pool

    return await (await get_pool()).fetchval("SELECT count(*) FROM tasks")


async def run_tools(api_url: str) -> dict:
    results = []
    tasks_before = await _task_count()
    async with httpx.AsyncClient(timeout=300) as client:
        for case in _load("golden/tool_calls.json"):
            started = time.monotonic()
            reply = await _post(
                client,
                f"{api_url}/api/v1/chat/tools",
                {"messages": [{"role": "user", "content": case["message"]}]},
            )
            used = reply.get("toolsUsed", []) if isinstance(reply, dict) else []
            names = [u["tool"] for u in used]
            expected = case["expect_tool"]
            tool_ok = (expected in names) if expected else not names
            args_text = json.dumps([u["arguments"] for u in used if u["tool"] == expected]).lower()
            args_ok = tool_ok and all(
                v.lower() in args_text for v in case["expect_args_contain"].values()
            )
            results.append(
                {
                    "id": case["id"],
                    "tools_used": names,
                    "tool_ok": tool_ok,
                    "args_ok": args_ok,
                    "latency_s": round(time.monotonic() - started, 1),
                }
            )
    no_writes = await _task_count() == tasks_before
    return {
        "metrics": {
            "cases": len(results),
            "tool_accuracy": metrics.rate([r["tool_ok"] for r in results]),
            "arg_accuracy": metrics.rate([r["args_ok"] for r in results]),
            "no_unconfirmed_writes": 1.0 if no_writes else 0.0,
            "mean_latency_s": round(metrics.mean([r["latency_s"] for r in results]), 1),
        },
        "cases": results,
    }


async def run_agent(api_url: str) -> dict:
    results = []
    tasks_before = await _task_count()
    async with httpx.AsyncClient(timeout=600) as client:
        for case in _load("golden/agent.json"):
            started = time.monotonic()
            reply = await _post(
                client, f"{api_url}/api/v1/agent/recommend", {"message": case["message"]}
            )
            reply = reply if isinstance(reply, dict) else {}
            route = reply.get("route")
            status = reply.get("status")
            company = (reply.get("proposedTask") or {}).get("companyName")
            results.append(
                {
                    "id": case["id"],
                    "error": _error(reply),
                    "route": route,
                    "status": status,
                    "company": company,
                    "route_ok": route == case["expect_route"],
                    "status_ok": status == case["expect_status"],
                    "company_ok": company == case["expect_company"],
                    "steps": len(reply.get("trace", [])),
                    "latency_s": round(time.monotonic() - started, 1),
                }
            )
    no_writes = await _task_count() == tasks_before
    return {
        "metrics": {
            "cases": len(results),
            "route_accuracy": metrics.rate([r["route_ok"] for r in results]),
            "status_accuracy": metrics.rate([r["status_ok"] for r in results]),
            "company_accuracy": metrics.rate([r["company_ok"] for r in results]),
            "no_unconfirmed_writes": 1.0 if no_writes else 0.0,
            "mean_steps": round(metrics.mean([r["steps"] for r in results]), 1),
            "mean_latency_s": round(metrics.mean([r["latency_s"] for r in results]), 1),
        },
        "cases": results,
    }


async def _post(client: httpx.AsyncClient, url: str, body: dict) -> dict | list:
    # A failed call counts as a failed case (and is flagged as an error), not a crash
    try:
        response = await client.post(url, json=body)
        if response.status_code >= 500:
            return {"error": f"HTTP {response.status_code}"}
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": str(exc)}


# ------------------------------------------------------------------- reporting


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=EVALS,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _environment() -> dict:
    return {
        "llm_provider": os.environ.get("LLM_PROVIDER", "ollama"),
        "ollama_model": os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"),
        "openrouter_model": os.environ.get("OPENROUTER_MODEL", "liquid/lfm-2.5-2.6b:free"),
        "embedding_model": os.environ.get("GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001"),
        "qdrant_collection": os.environ.get("QDRANT_COLLECTION", "document_chunks"),
        "guard_mode": os.environ.get("GUARD_MODE", "rules"),
    }


def compare(baseline: dict, current: dict) -> list[str]:
    """Returns one message per metric outside its tolerance (empty means reproduced)."""
    problems = []
    for suite, current_suite in current["suites"].items():
        base_suite = baseline["suites"].get(suite)
        if base_suite is None:
            problems.append(f"{suite}: not in the baseline")
            continue
        tolerance = baseline.get("tolerances", TOLERANCES)[suite]
        for name, value in current_suite["metrics"].items():
            if name in INFORMATIONAL:
                continue
            base_value = base_suite["metrics"].get(name)
            if base_value is None or not metrics.within_tolerance(base_value, value, tolerance):
                problems.append(
                    f"{suite}.{name}: baseline {base_value}, now {value} (tolerance ±{tolerance})"
                )
    return problems


def _error(reply: object) -> str | None:
    return reply.get("error") if isinstance(reply, dict) else None


def _print_table(report: dict) -> None:
    for suite, data in report["suites"].items():
        print(f"\n{suite}")
        for name, value in data["metrics"].items():
            print(f"  {name:<28} {value}")
        errored = [c["id"] for c in data["cases"] if c.get("error")]
        if errored:
            print(
                f"  WARNING: {len(errored)} case(s) errored (network or API), results not trustworthy: {', '.join(errored)}"
            )


async def _run(suites: list[str], api_url: str) -> dict:
    report: dict = {
        "schema": 1,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "environment": _environment(),
        "tolerances": TOLERANCES,
        "suites": {},
    }
    for suite in suites:
        if suite == "adversarial":
            report["suites"][suite] = run_adversarial()
        elif suite == "retrieval":
            report["suites"][suite] = await run_retrieval()
        elif suite == "tools":
            report["suites"][suite] = await run_tools(api_url)
        elif suite == "agent":
            report["suites"][suite] = await run_agent(api_url)
    from app.db import close_pool

    await close_pool()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--suites",
        nargs="+",
        choices=SUITES,
        default=None,
        help="default: all, or the suites in --check's baseline",
    )
    parser.add_argument("--out", help="write the report to this JSON file")
    parser.add_argument(
        "--check", help="compare against this baseline file; exit 1 if outside tolerance"
    )
    parser.add_argument("--api-url", default=os.environ.get("API_URL", "http://localhost:8001"))
    args = parser.parse_args()

    baseline = json.loads(Path(args.check).read_text()) if args.check else None
    suites = args.suites or (list(baseline["suites"]) if baseline else list(SUITES))
    report = asyncio.run(_run(suites, args.api_url))
    _print_table(report)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"\nwrote {args.out}")
    if baseline:
        problems = compare(baseline, report)
        print(
            "\nbaseline check:",
            "reproduced within tolerance" if not problems else "OUTSIDE tolerance",
        )
        for line in problems:
            print("  -", line)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
