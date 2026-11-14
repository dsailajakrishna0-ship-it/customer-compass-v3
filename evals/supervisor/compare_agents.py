#!/usr/bin/env python3
"""E3.3 (Python edition): the fixed pipeline (POST /agent/recommend) against the supervisor (POST /agent/supervise).

  python3 evals/supervisor/compare_agents.py             replay the recorded runs (no keys, no network)
  python3 evals/supervisor/compare_agents.py --record    ask the running API for what is not recorded yet
  python3 evals/supervisor/compare_agents.py --check     replay and fail if the counts differ from baseline.json

The cases are the ten golden agent cases (cases.json, the same file the Java edition runs; synthetic data), each run REPEATS times per arm. --record needs the API
running (API_URL, default http://localhost:8001) with the CRM documents and the farm-supply knowledge base ingested
and the keys set; MODEL (a label and the model sent with every request) and EMBEDDING_MODEL (a label) are recorded.
A failed or rate-limited call is retried with a wait; reruns skip what is recorded. RECORDED_PATH and BASELINE_PATH point at other files. Every run must leave the task
table unchanged (nothing is written before a confirm): the recorder checks that. Latencies are what the recording
run saw; every other number is a count and replays exactly.
"""

import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CASES = json.loads((HERE / "cases.json").read_text())
RECORDED = Path(os.environ.get("RECORDED_PATH", HERE / "recorded.json"))
BASELINE = Path(os.environ.get("BASELINE_PATH", HERE / "baseline.json"))
ARMS = {"pipeline": "/api/v1/agent/recommend", "supervisor": "/api/v1/agent/supervise"}
REPEATS = 2
LABEL = re.compile(r"E\d+")


def base() -> str:
    return os.environ.get("API_URL", "http://localhost:8001").rstrip("/")


def post(path: str, payload: dict) -> tuple[int, dict, float]:
    request = urllib.request.Request(
        base() + path, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            status, text = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read()
    return status, json.loads(text or b"null"), (time.monotonic() - started) * 1000


def task_count() -> int:
    with urllib.request.urlopen(base() + "/api/v1/tasks", timeout=30) as response:
        return len(json.loads(response.read()))


def compact(body: dict, ms: float, tasks_changed: bool) -> dict:
    run = {
        "ok": True,
        "ms": round(ms),
        "route": body.get("route"),
        "status": body.get("status"),
        "company": (body.get("company") or {}).get("name"),
        "tasks_changed": tasks_changed,
        "model_calls": len(body.get("llmCalls", [])),
        "flagged": (body.get("guardrail") or {}).get("flagged", False),
    }
    evidence = body.get("evidence") or []
    labels = {item["label"] for item in evidence}
    rec = body.get("recommendation") or {}
    cited = rec.get("evidence") or []
    run["evidence_items"] = len(evidence)
    run["farm_supply_items"] = sum(1 for item in evidence if "[agri-supply]" in str(item.get("source")))
    run["valid_citations"] = bool(cited) and all(c in labels for c in cited)
    review = body.get("review") or {}
    run["approved"] = bool(review.get("approved"))
    run["revisions"] = review.get("revisions", 0)
    sup = body.get("supervisor")
    if sup:
        turns = sup["turns"]
        run["turns"] = len(turns)
        run["model_decisions"] = sup["modelDecisions"]
        run["overrides"] = sum(1 for t in turns if "proposed" in t or "could not be read" in str(t.get("reason")))
        run["researcher_runs"] = sum(1 for t in turns if t["next"] == "researcher")
        run["own_queries"] = sum(1 for t in turns if t.get("query"))
    if body.get("route") == "direct":
        run["status"] = "direct"
    return run


def load() -> dict:
    return json.loads(RECORDED.read_text()) if RECORDED.exists() else {"meta": {}, "runs": {}}


def record() -> int:
    model = os.environ.get("MODEL") or None
    data = load()
    data["meta"] = {
        "model": model or "default model chain",
        "embedding_model": os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001 (the default)"),
        "recorded": time.strftime("%Y-%m-%d"),
        "repeats": REPEATS,
    }
    for arm, path in ARMS.items():
        runs = data["runs"].setdefault(arm, {})
        for case in CASES:
            for rep in range(1, REPEATS + 1):
                key = f"{case['id']}#{rep}"
                if runs.get(key, {}).get("ok"):
                    continue
                payload = {"message": case["message"]}
                if model:
                    payload["model"] = model
                for attempt in range(1, 7):
                    before = task_count()
                    status, body, ms = post(path, payload)
                    if status == 200:
                        runs[key] = compact(body, ms, task_count() != before)
                        break
                    wait = min(60, 10 * attempt)
                    print(f"  {arm} {key}: HTTP {status}, waiting {wait}s (attempt {attempt})", file=sys.stderr)
                    time.sleep(wait)
                else:
                    runs[key] = {"ok": False, "status": status, "error": str(body)[:200]}
                RECORDED.write_text(json.dumps(data, indent=1, ensure_ascii=False))
                print(f"{arm} {key} {'ok' if runs[key].get('ok') else 'FAILED'}", file=sys.stderr)
    return 0


def expected(case: dict, arm: str) -> str:
    return case["expect_pipeline" if arm == "pipeline" else "expect_supervisor"]


def table(data: dict) -> dict:
    out: dict = {}
    for arm in ARMS:
        rows = []
        for case in CASES:
            for rep in range(1, REPEATS + 1):
                run = data["runs"].get(arm, {}).get(f"{case['id']}#{rep}")
                if run and run.get("ok"):
                    rows.append((case, run))
        completed = [r for r in rows if r[1]["status"] == "completed"]
        t = {
            "runs": len(rows),
            "as_expected": sum(
                1
                for c, r in rows
                if r["status"] == expected(c, arm) and (c["expect_company"] is None or r["company"] == c["expect_company"])
            ),
            "completed": len(completed),
            "completed_valid_citations": sum(1 for _, r in completed if r["valid_citations"]),
            "completed_approved": sum(1 for _, r in completed if r["approved"]),
            "tasks_written": sum(1 for _, r in rows if r["tasks_changed"]),
            "flagged": sum(1 for _, r in rows if r["flagged"]),
            "evidence_per_completed": round(statistics.mean([r["evidence_items"] for _, r in completed]), 1) if completed else 0,
            "farm_supply_items_in_completed": sum(r["farm_supply_items"] for _, r in completed),
            "model_calls_per_completed": round(statistics.mean([r["model_calls"] for _, r in completed]), 2) if completed else 0,
            "model_calls_total": sum(r["model_calls"] for _, r in rows),
            "median_ms": round(statistics.median([r["ms"] for _, r in rows])) if rows else 0,
            "p95_ms": round(sorted(r["ms"] for _, r in rows)[max(0, int(len(rows) * 0.95) - 1)]) if rows else 0,
            "failed": sum(
                1 for c in CASES for rep in range(1, REPEATS + 1)
                if (x := data["runs"].get(arm, {}).get(f"{c['id']}#{rep}")) and not x.get("ok")
            ),
        }
        if arm == "supervisor":
            t["supervisor_turns_per_run"] = round(statistics.mean([r["turns"] for _, r in rows]), 1) if rows else 0
            t["model_decisions_total"] = sum(r["model_decisions"] for _, r in rows)
            t["overrides_by_code"] = sum(r["overrides"] for _, r in rows)
            t["runs_with_research"] = sum(1 for _, r in rows if r["researcher_runs"] > 0)
            t["own_search_queries"] = sum(r["own_queries"] for _, r in rows)
        out[arm] = t
    return out


def show(t: dict, data: dict) -> None:
    meta = data.get("meta", {})
    print(
        f"Chat model: {meta.get('model')}   embeddings: {meta.get('embedding_model')}   "
        f"recorded: {meta.get('recorded')}   cases: {len(CASES)} x {meta.get('repeats', REPEATS)} runs per arm\\n".replace("\\n", "\n")
    )
    print(f"{'':56}{'pipeline':>10}{'supervisor':>12}")
    rows = [
        ("runs as expected (status and company)", "as_expected", "runs"),
        ("analyses completed", "completed", None),
        ("completed with valid citations", "completed_valid_citations", "completed"),
        ("completed and approved by the reviewer", "completed_approved", "completed"),
        ("evidence items per completed run", "evidence_per_completed", None),
        ("farm-supply items shown to the analyst (completed)", "farm_supply_items_in_completed", None),
        ("model calls per completed run", "model_calls_per_completed", None),
        ("model calls in total", "model_calls_total", None),
        ("tasks written before a confirm (must be 0)", "tasks_written", None),
        ("runs flagged by the guard", "flagged", None),
        ("median ms per run", "median_ms", None),
        ("p95 ms per run", "p95_ms", None),
        ("failed requests", "failed", None),
    ]
    for label, key, of in rows:
        cells = []
        for arm in ARMS:
            v = t[arm][key]
            cells.append(f"{v}/{t[arm][of]}" if of else f"{v}")
        print(f"{label:56}{cells[0]:>10}{cells[1]:>12}")
    s = t["supervisor"]
    print(
        f"\nSupervisor: {s['supervisor_turns_per_run']} turns per run, {s['model_decisions_total']} model decisions in total, "
        f"{s['overrides_by_code']} overridden or unreadable, {s['runs_with_research']} runs used the researcher, "
        f"{s['own_search_queries']} own search queries"
    )


STABLE = [
    "runs", "as_expected", "completed", "completed_valid_citations", "completed_approved", "tasks_written",
    "flagged", "farm_supply_items_in_completed", "model_calls_total", "failed",
]
STABLE_SUPERVISOR = ["model_decisions_total", "overrides_by_code", "runs_with_research", "own_search_queries"]


def stable(t: dict) -> dict:
    out = {arm: {k: t[arm][k] for k in STABLE} for arm in ARMS}
    out["supervisor"].update({k: t["supervisor"][k] for k in STABLE_SUPERVISOR})
    return out


def main(argv: list[str]) -> int:
    if "--record" in argv:
        record()
    data = load()
    if not data["runs"]:
        print("Nothing recorded yet: run with --record against a running API.", file=sys.stderr)
        return 2
    t = table(data)
    show(t, data)
    if "--write-baseline" in argv:
        BASELINE.write_text(json.dumps(stable(t), indent=1))
        print("\nbaseline.json written")
    if "--check" in argv:
        if not BASELINE.exists():
            print("\nFAIL: there is no baseline.json yet: record, then run with --write-baseline", file=sys.stderr)
            return 1
        if json.loads(BASELINE.read_text()) != stable(t):
            print("\nFAIL: the table differs from baseline.json", file=sys.stderr)
            return 1
        print("\nOK: every count matches baseline.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
