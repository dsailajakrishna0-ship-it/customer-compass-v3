"""Stage 5.5: manual versus framework, one table per seam, replayable.

Run from the repo root (the `just` recipes do):

    just eval-frameworks          replay the recorded measurements (offline, free, no keys, deterministic)
    just eval-frameworks-record   measure again (needs Postgres with the demo data, Qdrant, GOOGLE_API_KEY and
                                  OPENROUTER_API_KEY; the framework packages are layered on by the recipe)

Three seams, each measured on the questions the repo already has, with both sides behind the same function:

  1. chunker    CHUNKER_IMPL    our fixed windows vs LangChain's RecursiveCharacterTextSplitter. The 19 sample
                                documents are cut both ways, embedded, and the 42 retrieval questions are
                                answered by cosine search in memory, so only the chunker differs.
  2. retrieval  RETRIEVAL_IMPL  our Qdrant query vs LangChain's QdrantVectorStore, dense search, the same
                                collection, the same 42 questions, the real `retrieve_relevant_chunks`.
  3. agent      AGENT_IMPL      our fixed LangGraph evidence steps vs a LangChain prebuilt tool-calling agent,
                                the 10 cases of golden/agent.json through POST /agent/recommend, twice each,
                                with one pinned small paid model on both sides.

What is read in replay mode is `evals/frameworks/*.json` only (what was measured, with the latencies and
token counts recorded at the time). Lines of code are counted from the source files in this checkout.

Exit code: 0 ok, 1 a number moved against the baseline (with --check), 2 a recording is missing or failed.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import inspect
import json
import os
import subprocess
import sys
import textwrap
import time
from datetime import UTC, datetime
from pathlib import Path

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS))
sys.path.insert(0, str(EVALS.parent / "apps" / "api-py"))
import metrics  # noqa: E402
from agentic_lib import MODEL, PRICE_IN_PER_M, PRICE_OUT_PER_M  # noqa: E402

DATA = EVALS / "frameworks"
GOLDEN_RETRIEVAL = EVALS / "golden" / "retrieval.json"
GOLDEN_AGENT = EVALS / "golden" / "agent.json"
BASELINE = EVALS / "baseline" / "frameworks-v1.json"
RUNS = EVALS / "runs"
RETRIEVAL_FETCH = 5
AGENT_REPEATS = 2
TOLERANCE = 1e-6  # replay is deterministic: any change means the recording changed

IMPLS = ("manual", "frameworks")


# ------------------------------------------------------------------------------------ small helpers


def _load(path: Path):
    return json.loads(path.read_text())


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, cwd=EVALS
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def branch_and_sha() -> tuple[str, str]:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("", "HEAD"):
        branch = (
            os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME") or "detached"
        )
    return branch, _git("rev-parse", "--short", "HEAD") or "unknown"


def code_lines(source: str) -> int:
    """Lines of code: not blank, not a comment, not part of a docstring."""
    source = textwrap.dedent(source)
    skip: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Module):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                skip.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    count = 0
    for number, line in enumerate(source.splitlines(), start=1):
        text = line.strip()
        if text and not text.startswith("#") and number not in skip:
            count += 1
    return count


def loc_of(*objects) -> int:
    return sum(code_lines(inspect.getsource(o)) for o in objects)


def lines_of_code() -> dict[str, dict[str, int]]:
    """What each side adds for each seam, counted from the source in this checkout."""
    from app.agent import workflow
    from app.frameworks import agent as lc_agent
    from app.frameworks import chunker as lc_chunker
    from app.frameworks import retriever as lc_retriever
    from app.rag import chunking, ingest, retrieve

    return {
        "chunker": {
            "manual": loc_of(chunking.chunk_text_manual),
            "frameworks": loc_of(lc_chunker),
        },
        "retrieval": {
            "manual": loc_of(retrieve._dense_points, retrieve._chunk),
            "frameworks": loc_of(lc_retriever, ingest._with_framework_metadata),
        },
        "agent": {
            "manual": loc_of(workflow.evidence, workflow.documents, workflow.analyze),
            "frameworks": loc_of(lc_agent),
        },
    }


# ------------------------------------------------------------------------------------ the tables


def _med(values: list[float]) -> float:
    return metrics.percentile(values, 50) if values else 0.0


def _p95(values: list[float]) -> float:
    return metrics.percentile(values, 95) if values else 0.0


def _ranking_metrics(ranked_by_id: dict[str, list[str]]) -> dict[str, float]:
    cases = _load(GOLDEN_RETRIEVAL)
    answerable = [c for c in cases if c["relevant"]]
    unanswerable = [c for c in cases if not c["relevant"]]
    ranks = [(c, ranked_by_id.get(c["id"], [])) for c in answerable]
    return {
        "recall_at_1": metrics.mean(
            [metrics.recall_at_k(r, set(c["relevant"]), 1) for c, r in ranks]
        ),
        "recall_at_3": metrics.mean(
            [metrics.recall_at_k(r, set(c["relevant"]), 3) for c, r in ranks]
        ),
        "recall_at_5": metrics.mean(
            [metrics.recall_at_k(r, set(c["relevant"]), 5) for c, r in ranks]
        ),
        "mrr": metrics.mean([metrics.reciprocal_rank(r, set(c["relevant"])) for c, r in ranks]),
        "unanswerable_declined": float(
            sum(1 for c in unanswerable if not ranked_by_id.get(c["id"], []))
        ),
    }


def chunker_table(data: dict) -> dict[str, dict[str, float]]:
    table = {}
    for impl in IMPLS:
        d = data["chunkers"][impl]
        sizes = d["sizes"]
        row = {
            "chunks": float(len(sizes)),
            "median_chars": _med(sizes),
            "short_chunks_under_100": float(sum(1 for s in sizes if s < 100)),
            "mid_word_cuts": float(d["mid_word_cuts"]),
        }
        row.update(_ranking_metrics(d["ranked"]))
        del row[
            "unanswerable_declined"
        ]  # no similarity floor in the in-memory search: not meaningful
        table[impl] = row
    return table


def retrieval_table(data: dict) -> dict[str, dict[str, float]]:
    manual = data["impls"]["manual"]
    table = {}
    for impl in IMPLS:
        cases = data["impls"][impl]
        row = _ranking_metrics({k: v["ranked"] for k, v in cases.items()})
        ms = [v["ms"] for v in cases.values()]
        row.update(
            same_chunks_as_manual=float(
                sum(1 for k, v in cases.items() if v["chunk_ids"] == manual[k]["chunk_ids"])
            ),
            questions=float(len(cases)),
            median_ms=_med(ms),
            p95_ms=_p95(ms),
        )
        table[impl] = row
    return table


def agent_table(data: dict) -> dict[str, dict[str, float]]:
    table = {}
    for impl in IMPLS:
        runs = data["impls"][impl]
        analysed = [r for r in runs if r["status"] == "completed"]
        cost = (
            sum(r["tokens_in"] * PRICE_IN_PER_M + r["tokens_out"] * PRICE_OUT_PER_M for r in runs)
            / 1_000_000
        )
        table[impl] = {
            "runs": float(len(runs)),
            "outcome_as_expected": float(sum(1 for r in runs if r["as_expected"])),
            "completed": float(len(analysed)),
            "valid_citations": float(sum(1 for r in analysed if r["citations_valid"])),
            "reviewer_approved": float(sum(1 for r in analysed if r["approved"])),
            "revisions_mean": metrics.mean([float(r["revisions"]) for r in analysed]),
            "evidence_items_mean": metrics.mean([float(r["evidence_n"]) for r in analysed]),
            "evidence_steps_mean": metrics.mean([float(r["evidence_steps"]) for r in analysed]),
            "model_calls_mean": metrics.mean([float(r["model_calls"]) for r in analysed]),
            "tokens_mean": metrics.mean(
                [float(r["tokens_in"] + r["tokens_out"]) for r in analysed]
            ),
            "median_ms": _med([float(r["wall_ms"]) for r in analysed]),
            "p95_ms": _p95([float(r["wall_ms"]) for r in analysed]),
            "tasks_written_by_recommend": float(sum(r["tasks_written"] for r in runs)),
            "fallback_used": float(sum(1 for r in runs if r["fallback_used"])),
            "cost_usd": cost,
        }
    return table


def all_tables() -> dict:
    return {
        "chunker": chunker_table(_load(DATA / "chunker.json")),
        "retrieval": retrieval_table(_load(DATA / "retrieval.json")),
        "agent": agent_table(_load(DATA / "agent.json")),
    }


# ------------------------------------------------------------------------------------ printing

LABELS = {
    "chunks": "chunks from the 19 documents",
    "median_chars": "median chunk size (characters)",
    "short_chunks_under_100": "chunks under 100 characters",
    "mid_word_cuts": "chunks cut in the middle of a word",
    "recall_at_1": "recall@1",
    "recall_at_3": "recall@3",
    "recall_at_5": "recall@5",
    "mrr": "MRR",
    "unanswerable_declined": "unanswerable questions declined (of 6)",
    "same_chunks_as_manual": "questions with the same chunks as manual (of 42)",
    "questions": "questions",
    "median_ms": "median ms",
    "p95_ms": "p95 ms",
    "runs": "runs",
    "outcome_as_expected": "status and company as expected",
    "completed": "analyses completed",
    "valid_citations": "completed with valid citations",
    "reviewer_approved": "completed and reviewer-approved",
    "revisions_mean": "revisions per completed run",
    "evidence_items_mean": "evidence items per completed run",
    "evidence_steps_mean": "evidence tool and code steps per completed run",
    "model_calls_mean": "model calls per completed run",
    "tokens_mean": "tokens per completed run",
    "tasks_written_by_recommend": "tasks written by recommend (must be 0)",
    "fallback_used": "runs where a fallback model answered",
    "cost_usd": "cost (US$)",
}


def _fmt(key: str, value: float) -> str:
    if key.endswith("_ms"):
        return f"{value:.0f}"
    if key in ("cost_usd",):
        return f"{value:.4f}"
    if key in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr"):
        return f"{value:.3f}"
    if float(value).is_integer():
        return f"{int(value)}"
    return f"{value:.2f}"


def print_table(title: str, table: dict, loc: dict[str, int]) -> None:
    keys = list(next(iter(table.values())))
    width = max(len(LABELS.get(k, k)) for k in keys + ["lines of code (what each side adds)"])
    print(f"\n{title}")
    print(f"{'':<{width}}  {'manual':>10}  {'frameworks':>10}")
    for key in keys:
        print(
            f"{LABELS.get(key, key):<{width}}  {_fmt(key, table['manual'][key]):>10}  "
            f"{_fmt(key, table['frameworks'][key]):>10}"
        )
    print(
        f"{'lines of code (what each side adds)':<{width}}  {loc['manual']:>10}  {loc['frameworks']:>10}"
    )


def print_report(tables: dict, loc: dict) -> None:
    branch, sha = branch_and_sha()
    print(f"Stage 5.5 framework comparison  branch {branch} @ {sha}  agent model {MODEL}")
    print_table(
        "1. chunker (CHUNKER_IMPL), dense search in memory", tables["chunker"], loc["chunker"]
    )
    print_table(
        "2. retrieval (RETRIEVAL_IMPL), dense search in Qdrant",
        tables["retrieval"],
        loc["retrieval"],
    )
    print_table("3. agent (AGENT_IMPL), 10 cases x 2 repeats", tables["agent"], loc["agent"])


# ------------------------------------------------------------------------------------ the check


def check(tables: dict) -> list[str]:
    if not BASELINE.exists():
        return [f"no baseline at {BASELINE}"]
    base = _load(BASELINE)["tables"]
    problems = []
    for seam, impls in tables.items():
        for impl, row in impls.items():
            for key, value in row.items():
                saved = base.get(seam, {}).get(impl, {}).get(key)
                if saved is None or not metrics.within_tolerance(saved, value, TOLERANCE):
                    problems.append(f"{seam}/{impl}/{key}: baseline {saved}, now {value}")
    return problems


# ------------------------------------------------------------------------------------ recording
# Everything below needs the stack and keys; replay never imports it.


def _versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for name in (
        "langchain",
        "langchain-core",
        "langchain-text-splitters",
        "langchain-qdrant",
        "langgraph",
    ):
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "not installed"
    return out


async def _embed(texts: list[str], batch: int = 10) -> list[list[float]]:
    """Embeds in small batches and waits out Google's free-tier 429s (recording only)."""
    from app.rag.embeddings import EmbeddingsUnavailableError, embed_texts

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch):
        for attempt in range(8):
            try:
                vectors += await embed_texts(texts[start : start + batch])
                break
            except EmbeddingsUnavailableError as exc:
                if "429" not in str(exc) or attempt == 7:
                    raise
                await asyncio.sleep(15 * (attempt + 1))
        await asyncio.sleep(1)
    return vectors


def _unit(vector: list[float]) -> list[float]:
    norm = sum(x * x for x in vector) ** 0.5 or 1.0
    return [x / norm for x in vector]


def _name(source_path: str) -> str:
    return Path(source_path).name


async def record_chunker() -> dict:
    from app.frameworks.chunker import chunk_text_frameworks
    from app.rag.chunking import chunk_text_manual
    from app.rag.embeddings import embedding_model_id
    from app.rag.ingest import _load_documents

    documents = _load_documents()
    questions = _load(GOLDEN_RETRIEVAL)
    question_vectors = [_unit(v) for v in await _embed([q["question"] for q in questions])]
    out: dict = {"embedding_model": embedding_model_id(), "versions": _versions(), "chunkers": {}}
    for impl, cut in (("manual", chunk_text_manual), ("frameworks", chunk_text_frameworks)):
        texts: list[str] = []
        owners: list[str] = []
        sizes: list[int] = []
        mid_word = 0
        for doc in documents:
            for segment in doc.segments:
                trimmed = segment.text.strip()
                for c in cut(segment.text):
                    texts.append(c.content)
                    owners.append(_name(doc.source_path))
                    sizes.append(len(c.content))
                    if (
                        c.char_end < len(trimmed)
                        and trimmed[c.char_end - 1].isalnum()
                        and trimmed[c.char_end].isalnum()
                    ):
                        mid_word += 1
        vectors = [_unit(v) for v in await _embed(texts)]
        ranked: dict[str, list[str]] = {}
        for q, vec in zip(questions, question_vectors, strict=True):
            scores = [sum(a * b for a, b in zip(v, vec, strict=True)) for v in vectors]
            order = sorted(range(len(scores)), key=lambda i: -scores[i])
            ranked[q["id"]] = metrics.dedupe_keep_order([owners[i] for i in order[:20]])[
                :RETRIEVAL_FETCH
            ]
        out["chunkers"][impl] = {"sizes": sizes, "mid_word_cuts": mid_word, "ranked": ranked}
        print(f"  chunker {impl}: {len(sizes)} chunks", flush=True)
    return out


async def record_retrieval() -> dict:
    from qdrant_client import QdrantClient

    import app.frameworks.retriever as lc_retriever
    import app.rag.retrieve as manual_retrieve
    from app.config import get_settings, reset_settings
    from app.db import get_pool
    from app.rag.embeddings import embedding_model_id
    from app.rag.retrieve import get_point_count, retrieve_relevant_chunks

    if await get_point_count() == 0:
        raise SystemExit(
            "Qdrant has no documents: ingest first (RETRIEVAL_IMPL=frameworks, see the recipe)."
        )
    pool = await get_pool()
    questions = _load(GOLDEN_RETRIEVAL)
    # Each question is embedded once (paced, free tier) and both sides then search with that vector, so the
    # timings below are the search path only: the Gemini call is the same on both sides and would swamp it.
    vectors = dict(
        zip(
            [q["question"] for q in questions],
            await _embed([q["question"] for q in questions]),
            strict=True,
        )
    )

    async def cached_embed(text: str) -> list[float]:
        return vectors[text]

    real_embed = manual_retrieve.embed_text, lc_retriever.embed_text
    manual_retrieve.embed_text = cached_embed  # type: ignore[assignment]
    lc_retriever.embed_text = cached_embed  # type: ignore[assignment]

    checks = {"n": 0}
    original = QdrantClient.get_collection

    def counting(self, *args, **kwargs):
        checks["n"] += 1
        return original(self, *args, **kwargs)

    QdrantClient.get_collection = counting  # type: ignore[method-assign]
    out: dict = {"embedding_model": embedding_model_id(), "versions": _versions(), "impls": {}}
    try:
        for impl in IMPLS:
            os.environ["RETRIEVAL_IMPL"] = impl
            reset_settings()
            assert get_settings().retrieval_impl == impl
            cases: dict = {}
            for case in questions:
                company_id = None
                if case["company"]:
                    company_id = await pool.fetchval(
                        "SELECT id FROM companies WHERE name = $1", case["company"]
                    )
                # one untimed call warms connections; the timed figure is the median of five
                await retrieve_relevant_chunks(case["question"], company_id, RETRIEVAL_FETCH)
                times: list[float] = []
                for _ in range(5):
                    checks["n"] = 0
                    started = time.monotonic()
                    chunks = await retrieve_relevant_chunks(
                        case["question"], company_id, RETRIEVAL_FETCH
                    )
                    times.append((time.monotonic() - started) * 1000)
                cases[case["id"]] = {
                    "ranked": metrics.dedupe_keep_order([_name(c.source_path) for c in chunks]),
                    "chunk_ids": [str(c.chunk_id) for c in chunks],
                    "ms": sorted(times)[2],
                    "collection_checks": checks["n"],
                }
            out["impls"][impl] = cases
            print(f"  retrieval {impl}: {len(cases)} questions", flush=True)
    finally:
        QdrantClient.get_collection = original  # type: ignore[method-assign]
        manual_retrieve.embed_text, lc_retriever.embed_text = real_embed  # type: ignore[assignment]
        os.environ["RETRIEVAL_IMPL"] = "manual"
        reset_settings()
    return out


async def record_agent() -> dict:
    import httpx

    import app.routes.agent as agent_route
    from app.config import reset_settings
    from app.db import get_pool
    from app.main import app

    real_generate = agent_route.generate
    counters = {"in": 0, "out": 0, "fallback": False}

    async def counting_generate(*args, **kwargs):
        result = await real_generate(*args, **kwargs)
        counters["in"] += result.tokens_in or 0
        counters["out"] += result.tokens_out or 0
        counters["fallback"] = counters["fallback"] or result.fallback_used
        return result

    agent_route.generate = counting_generate
    pool = await get_pool()
    out: dict = {"model": MODEL, "versions": _versions(), "impls": {}}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://x", timeout=240
        ) as client:
            for impl in IMPLS:
                os.environ["AGENT_IMPL"] = impl
                reset_settings()
                runs: list[dict] = []
                for case in _load(GOLDEN_AGENT):
                    for repeat in range(AGENT_REPEATS):
                        counters.update({"in": 0, "out": 0, "fallback": False})
                        tasks_before = await pool.fetchval("SELECT COUNT(*) FROM tasks")
                        started = time.monotonic()
                        reply = await client.post(
                            "/api/v1/agent/recommend",
                            json={"message": case["message"], "model": MODEL},
                        )
                        wall_ms = int((time.monotonic() - started) * 1000)
                        tasks_after = await pool.fetchval("SELECT COUNT(*) FROM tasks")
                        runs.append(
                            _agent_record(
                                case, repeat, reply, wall_ms, counters, tasks_after - tasks_before
                            )
                        )
                        print(
                            f"  agent {impl} {case['id']} #{repeat + 1}: {runs[-1]['status']} {wall_ms} ms",
                            flush=True,
                        )
                out["impls"][impl] = runs
    finally:
        agent_route.generate = real_generate
        os.environ["AGENT_IMPL"] = "manual"
        reset_settings()
    return out


def _agent_record(
    case: dict, repeat: int, reply, wall_ms: int, counters: dict, written: int
) -> dict:
    body = reply.json() if reply.status_code == 200 else {}
    route = body.get("route")
    status = body.get("status") or ("direct" if route == "direct" else f"http_{reply.status_code}")
    evidence = body.get("evidence", [])
    labels = {item["label"] for item in evidence}
    rec = body.get("recommendation") or {}
    cited = rec.get("evidence", [])
    steps = body.get("trace", [])
    company = (body.get("company") or {}).get("name")
    expected_status = case["expect_status"] or "direct"
    as_expected = (
        route == case["expect_route"]
        and (case["expect_route"] == "direct" or status == expected_status)
        and company == case["expect_company"]
    )
    return {
        "case": case["id"],
        "repeat": repeat,
        "route": route,
        "status": status,
        "company": company,
        "as_expected": bool(as_expected),
        "evidence_n": len(evidence),
        "citations_valid": bool(cited) and all(label in labels for label in cited),
        "approved": bool((body.get("review") or {}).get("approved")),
        "revisions": (body.get("review") or {}).get("revisions", 0),
        "trace": [s["name"] for s in steps],
        "evidence_steps": sum(
            1 for s in steps if s["kind"] in ("tool", "code") and s["name"] != "identify_company"
        ),
        "model_calls": len(body.get("llmCalls", [])),
        "tokens_in": counters["in"],
        "tokens_out": counters["out"],
        "wall_ms": wall_ms,
        "tasks_written": written,
        "fallback_used": bool(counters["fallback"]),
        # why a request failed (a 503 from the model chain, for example); not set on success
        "error": None if reply.status_code == 200 else str(body.get("error") or reply.text)[:200],
    }


def record(which: list[str]) -> None:
    jobs = {"chunker": record_chunker, "retrieval": record_retrieval, "agent": record_agent}
    for name in which:
        print(f"recording {name} ...", flush=True)
        data = asyncio.run(jobs[name]())
        data["recorded_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
        _save(DATA / f"{name}.json", data)


# ------------------------------------------------------------------------------------ main


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--mode", choices=("replay", "record"), default="replay")
    parser.add_argument("--only", choices=("chunker", "retrieval", "agent"), action="append")
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if a number moved against the baseline"
    )
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()

    if args.mode == "record":
        record(args.only or ["chunker", "retrieval", "agent"])
    missing = [n for n in ("chunker", "retrieval", "agent") if not (DATA / f"{n}.json").exists()]
    if missing:
        print(
            f"missing recordings: {', '.join(missing)} (run `just eval-frameworks-record`)",
            file=sys.stderr,
        )
        return 2

    tables = all_tables()
    loc = lines_of_code()
    print_report(tables, loc)
    branch, sha = branch_and_sha()
    RUNS.mkdir(exist_ok=True)
    (RUNS / f"frameworks-{sha}.json").write_text(
        json.dumps(
            {"branch": branch, "sha": sha, "tables": tables, "loc": loc}, indent=1, sort_keys=True
        )
    )
    if args.write_baseline:
        _save(BASELINE, {"tables": tables, "note": "Stage 5.5; lines of code are not baselined"})
        print(f"\nbaseline written to {BASELINE}")
    if args.check:
        problems = check(tables)
        if problems:
            print("\nmoved against the baseline:", file=sys.stderr)
            for p in problems:
                print(f"  {p}", file=sys.stderr)
            return 1
        print("\nOK: every number matches evals/baseline/frameworks-v1.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
