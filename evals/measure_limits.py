"""Measures how long the agent workflow really takes, to check its hard limits (steps and seconds).

The limits (AGENT_MAX_STEPS, AGENT_TIMEOUT_SECONDS) were chosen for a slow local model. With hosted
free models the right numbers may differ, so this runs the agent golden cases several times against a
running API and reports how close real runs come to the limits. It only *suggests* new values; a
person decides (docs/adr/0012-agent-limits.md).

    uv run --project apps/api-py python evals/measure_limits.py --runs 3 --out evals/baseline/limits.json

Needs the stack up, documents ingested, and OPENROUTER_API_KEY, like any other chat call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS))
sys.path.insert(0, str(EVALS.parent / "apps" / "api-py"))
import metrics  # noqa: E402

TIMEOUT_HEADROOM = 1.5  # suggested timeout covers the slowest run seen plus 50%
TIMEOUT_STEP_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 900  # the client must outlast the server's own agent timeout


def agent_cases() -> list[dict]:
    """The golden cases that run the whole workflow to a proposed task."""
    cases = json.loads((EVALS / "golden" / "agent.json").read_text())
    return [c for c in cases if c["expect_route"] == "agent" and c["expect_status"] == "completed"]


async def measure(
    client: httpx.AsyncClient, api_url: str, cases: list[dict], runs: int
) -> list[dict]:
    results = []
    for case in cases:
        for attempt in range(1, runs + 1):
            started = time.monotonic()
            row: dict = {"case": case["id"], "attempt": attempt}
            try:
                response = await client.post(
                    f"{api_url}/api/v1/agent/recommend", json={"message": case["message"]}
                )
                body = response.json()
                trace = (
                    body.get("trace", [])
                    if isinstance(body, dict) and response.status_code < 500
                    else []
                )
                row.update(
                    status=body.get("status")
                    if isinstance(body, dict) and response.status_code < 500
                    else None,
                    error=None if response.status_code < 500 else f"HTTP {response.status_code}",
                    steps=len(trace),
                    agent_seconds=[
                        s["duration_ms"] / 1000 for s in trace if s.get("kind") == "agent"
                    ],
                )
            except (httpx.HTTPError, ValueError) as exc:
                row.update(status=None, error=str(exc), steps=0, agent_seconds=[])
            row["seconds"] = round(time.monotonic() - started, 2)
            results.append(row)
    return results


def summarise(rows: list[dict], max_steps: int, timeout_seconds: float) -> dict:
    """Turns raw runs into the numbers the limits decision needs."""
    ok = [r for r in rows if r["error"] is None]
    done = [r for r in ok if r["status"] == "completed"]
    statuses: dict[str, int] = {}
    for row in ok:
        statuses[str(row["status"])] = statuses.get(str(row["status"]), 0) + 1
    out: dict = {
        "runs": len(rows),
        "errored": len(rows) - len(ok),
        "statuses": statuses,
        "limits": {"max_steps": max_steps, "timeout_seconds": timeout_seconds},
    }
    if not done:
        return out
    seconds = [r["seconds"] for r in done]
    calls = [s for r in done for s in r["agent_seconds"]]
    steps = [r["steps"] for r in done]
    slowest = max(seconds)
    out.update(
        wall_seconds={
            "p50": metrics.percentile(seconds, 50),
            "p90": metrics.percentile(seconds, 90),
            "max": slowest,
        },
        one_agent_call_seconds={
            "p50": metrics.percentile(calls, 50),
            "p90": metrics.percentile(calls, 90),
            "max": max(calls),
        }
        if calls
        else None,
        trace_steps={"typical": metrics.percentile(steps, 50), "max": max(steps)},
        share_of_timeout_used_at_p90=round(metrics.percentile(seconds, 90) / timeout_seconds, 2),
        suggestion={
            "timeout_seconds": metrics.round_up_to(
                slowest * TIMEOUT_HEADROOM, TIMEOUT_STEP_SECONDS
            ),
            "reason": f"the slowest completed run took {slowest:.0f}s; suggest that plus {int((TIMEOUT_HEADROOM - 1) * 100)}%, rounded up to {TIMEOUT_STEP_SECONDS}s",
            "note": "a suggestion only: a person decides, and the step limit is a safety rule, not a speed setting",
        },
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--runs", type=int, default=3, help="runs per case")
    parser.add_argument("--out", help="write the report to this JSON file")
    parser.add_argument("--api-url", default=os.environ.get("API_URL", "http://localhost:8001"))
    args = parser.parse_args()

    from app.config import get_settings

    settings = get_settings()

    async def run() -> list[dict]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            return await measure(client, args.api_url, agent_cases(), args.runs)

    rows = asyncio.run(run())
    report = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "chat_model": f"openrouter/{settings.default_openrouter_model}",
        "summary": summarise(rows, settings.agent_max_steps, settings.agent_timeout_seconds),
        "runs": rows,
    }
    print(json.dumps(report["summary"], indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nwrote {args.out}")
    if report["summary"]["errored"] == report["summary"]["runs"]:
        print(
            "\nEvery run failed. Is the stack up, and is OPENROUTER_API_KEY set?", file=sys.stderr
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
