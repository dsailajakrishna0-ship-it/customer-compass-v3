"""E1.3 (Python edition): compare the three ways POST /api/v1/chat/multi can decide where to search (route, all, agent) on the same 24 labelled questions the Java edition used.

  python3 evals/knowledge-bases/compare_strategies.py             replay the recorded answers (no keys, no network)
  python3 evals/knowledge-bases/compare_strategies.py --record    ask the running API for what is not recorded yet
  python3 evals/knowledge-bases/compare_strategies.py --check     replay and fail if the table differs from baseline.json

--record needs the API running (API_URL, default http://localhost:8001) with the CRM documents and the farm-supply
knowledge base ingested and the keys set. MODEL picks the model for the router, the answer and the agent, and EMBEDDING_MODEL names the embedding model the API runs with (both are only recorded as labels). A failed or rate
limited call is retried with a wait; reruns skip what is already recorded, so an interrupted run can be resumed.
Latencies are what the recording run saw; every other number is a count and replays exactly.
"""

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
QUESTIONS = json.loads((HERE / "questions.json").read_text())
RECORDED = HERE / "recorded.json"
BASELINE = HERE / "baseline.json"
STRATEGIES = ["route", "all", "agent"]
NOT_FOUND = "I could not find any ingested documents relevant to that question."


def load() -> dict:
    return json.loads(RECORDED.read_text()) if RECORDED.exists() else {"meta": {}, "runs": {}}


def ask(strategy: str, question: str, model: str | None) -> tuple[int, dict, float]:
    base = os.environ.get("API_URL", "http://localhost:8001").rstrip("/")
    payload = {"messages": [{"role": "user", "content": question}], "strategy": strategy}
    if model:
        payload["model"] = model
    request = urllib.request.Request(
        base + "/api/v1/chat/multi", json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            status, text = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read()
    return status, json.loads(text or b"null"), (time.monotonic() - started) * 1000


def compact(body: dict) -> dict:
    return {
        "message": body["message"],
        "citations": [
            {"kb": c["knowledgeBase"], "doc": Path(c["sourcePath"]).name} for c in body["citations"]
        ],
        "searched": body["routing"]["searched"],
        "modelCalls": body["routing"]["modelCalls"],
        "reason": body["routing"].get("reason"),
        "tools": [(t["knowledgeBase"], t["query"]) for t in body["routing"].get("toolsUsed", [])],
        "flagged": body["guardrail"]["flagged"],
    }


def record() -> int:
    model = os.environ.get("MODEL") or None
    data = load()
    data["meta"] = {
        "model": model or "default model chain",
        "embedding_model": os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001 (the default)"),
        "recorded": time.strftime("%Y-%m-%d"),
    }
    for strategy in STRATEGIES:
        runs = data["runs"].setdefault(strategy, {})
        for q in QUESTIONS:
            if q["id"] in runs and runs[q["id"]].get("ok"):
                continue
            for attempt in range(1, 7):
                status, body, ms = ask(strategy, q["question"], model)
                if status == 200:
                    runs[q["id"]] = {"ok": True, "ms": round(ms), **compact(body)}
                    break
                wait = min(60, 10 * attempt)
                print(f"  {strategy} {q['id']}: HTTP {status}, waiting {wait}s (attempt {attempt})", file=sys.stderr)
                time.sleep(wait)
            else:
                runs[q["id"]] = {"ok": False, "status": status, "error": str(body)[:200]}
            RECORDED.write_text(json.dumps(data, indent=1, ensure_ascii=False))
            print(f"{strategy} {q['id']} {'ok' if runs[q['id']].get('ok') else 'FAILED'}", file=sys.stderr)
    return 0


def declined(run: dict) -> bool:
    return not run["citations"]


def score(run: dict, q: dict) -> dict:
    cited_kbs = {c["kb"] for c in run["citations"]}
    expected = set(q["expected_kbs"])
    # a hit needs a relevant document from every knowledge base the question belongs to
    hit = bool(expected) and all(
        any(c["kb"] == kb and c["doc"] in docs for c in run["citations"]) for kb, docs in q["relevant"].items()
    )
    return {
        "hit": hit,
        "searched_exact": set(run["searched"]) == expected,
        "searched_all": set(run["searched"]) >= expected,
        "off_target": sum(1 for c in run["citations"] if c["kb"] not in expected),
        "citations": len(run["citations"]),
        "declined": declined(run),
        "cited_exact": cited_kbs == expected,
    }


def table(data: dict) -> dict:
    out: dict = {}
    for strategy in STRATEGIES:
        runs = data["runs"].get(strategy, {})
        rows = []
        for q in QUESTIONS:
            run = runs.get(q["id"])
            if run and run.get("ok"):
                rows.append((q, run, score(run, q)))
        answerable = [r for r in rows if r[0]["kind"] != "neither"]
        by_kind = {}
        for kind in ("crm", "agri", "both"):
            sel = [r for r in answerable if r[0]["kind"] == kind]
            by_kind[kind] = {"hit": sum(r[2]["hit"] for r in sel), "of": len(sel)}
        neither = [r for r in rows if r[0]["kind"] == "neither"]
        out[strategy] = {
            "questions": len(rows),
            "hit": sum(r[2]["hit"] for r in answerable),
            "answerable": len(answerable),
            "hit_by_kind": by_kind,
            "searched_exactly_the_right_knowledge_bases": sum(r[2]["searched_exact"] for r in rows),
            "searched_at_least_the_right_ones": sum(r[2]["searched_all"] for r in rows),
            "citations_from_the_wrong_knowledge_base": sum(r[2]["off_target"] for r in rows),
            "citations_total": sum(r[2]["citations"] for r in rows),
            "neither_declined": sum(r[2]["declined"] for r in neither),
            "neither": len(neither),
            "model_calls_mean": round(statistics.mean(r[1]["modelCalls"] for r in rows), 2) if rows else 0,
            "model_calls_total": sum(r[1]["modelCalls"] for r in rows),
            "median_ms": round(statistics.median(r[1]["ms"] for r in rows)) if rows else 0,
            "p95_ms": round(sorted(r[1]["ms"] for r in rows)[max(0, int(len(rows) * 0.95) - 1)]) if rows else 0,
            "failed": sum(1 for q in QUESTIONS if runs.get(q["id"]) and not runs[q["id"]].get("ok")),
        }
    return out


def show(t: dict, data: dict) -> None:
    meta = data.get("meta", {})
    print(
        f"Chat model: {meta.get('model')}   embeddings: {meta.get('embedding_model')}   "
        f"recorded: {meta.get('recorded')}   questions: {len(QUESTIONS)}\n"
    )
    head = f"{'':58}" + "".join(f"{s:>9}" for s in STRATEGIES)
    print(head)

    def row(label, fn):
        print(f"{label:58}" + "".join(f"{fn(t[s]):>9}" for s in STRATEGIES))

    row("answerable questions: right sources found", lambda x: f"{x['hit']}/{x['answerable']}")
    for kind, label in (("crm", "  of them, CRM-only questions"), ("agri", "  of them, farm-supply-only questions"), ("both", "  of them, questions that need both")):
        row(label, lambda x, k=kind: f"{x['hit_by_kind'][k]['hit']}/{x['hit_by_kind'][k]['of']}")
    row("searched exactly the right knowledge bases (all questions)", lambda x: f"{x['searched_exactly_the_right_knowledge_bases']}/{x['questions']}")
    row("searched at least the right ones", lambda x: f"{x['searched_at_least_the_right_ones']}/{x['questions']}")
    row("citations from the wrong knowledge base", lambda x: f"{x['citations_from_the_wrong_knowledge_base']}/{x['citations_total']}")
    row("no-corpus questions with no sources cited", lambda x: f"{x['neither_declined']}/{x['neither']}")
    row("model calls per question (mean)", lambda x: x["model_calls_mean"])
    row("median ms per question", lambda x: x["median_ms"])
    row("p95 ms per question", lambda x: x["p95_ms"])
    row("failed requests", lambda x: x["failed"])


STABLE = [
    "questions", "hit", "answerable", "hit_by_kind", "searched_exactly_the_right_knowledge_bases",
    "searched_at_least_the_right_ones", "citations_from_the_wrong_knowledge_base", "citations_total",
    "neither_declined", "neither", "model_calls_total", "failed",
]


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
        BASELINE.write_text(json.dumps({s: {k: t[s][k] for k in STABLE} for s in STRATEGIES}, indent=1))
        print("\nbaseline.json written")
    if "--check" in argv:
        expected = json.loads(BASELINE.read_text())
        current = {s: {k: t[s][k] for k in STABLE} for s in STRATEGIES}
        if expected != current:
            print("\nFAIL: the table differs from baseline.json", file=sys.stderr)
            return 1
        print("\nOK: every count matches baseline.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
