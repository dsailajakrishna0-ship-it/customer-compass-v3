"""Stage 5.4: agentic retrieval against plain hybrid search, one before/after table.

Run from the repo root (the `just` recipes do):

    just eval-agentic           replay the recorded searches and model calls (offline, free, no keys, deterministic)
    just eval-agentic-record    record what is missing (needs the stack, GOOGLE_API_KEY and OPENROUTER_API_KEY)

The same 42 questions as the retrieval baseline (36 answerable, 6 not), two arms:
  - plain:   hybrid search, the top 4 chunks go to the answering model (what POST /chat/rag does by default),
  - agentic: the same search, then the relevance check, at most one query rewrite and retry, the same answer
             step, and the grounding check on the answer (`AGENTIC_RETRIEVAL=on`).
Every model-backed step, in both arms, uses one pinned small paid model (see agentic_lib.py). Both arms share
the first search; the plain arm's grounding check is measured for the comparison but not counted in its cost.

Exit code: 0 ok, 1 a number moved against the baseline (with --check), 2 a recording is missing in replay mode
or a call kept failing while recording.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS))
sys.path.insert(0, str(EVALS.parent / "apps" / "api-py"))
import agentic_lib as lib  # noqa: E402

from app.guardrails.prompt_guard import (  # noqa: E402
    scan_and_neutralize,
    wrap_untrusted_context,
)
from app.rag import agentic  # noqa: E402
from app.rag.retrieve import DEFAULT_TOP_K, RetrievedChunk, build_context  # noqa: E402
from app.routes.chat import GROUNDED_SYSTEM_PROMPT  # noqa: E402

lib.DECLINE_PHRASES = agentic.REFUSAL_PHRASES  # one list of refusal wording, the app's

GOLDEN = EVALS / "golden" / "retrieval.json"
BASELINE = EVALS / "baseline" / "agentic-v1.json"
RUNS = EVALS / "runs"
MODE_OF_SEARCH = "hybrid"
NONE_FOUND = "I could not find any ingested documents relevant to that question."


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


# ---- searches -----------------------------------------------------------------------------------
def _chunk(row: dict) -> RetrievedChunk:
    return RetrievedChunk(**row)


def _row(chunk: RetrievedChunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "document_title": chunk.document_title,
        "source_path": chunk.source_path,
        "doc_type": chunk.doc_type,
        "company_name": chunk.company_name,
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "similarity": chunk.similarity,
        "page": chunk.page,
        "sheet": chunk.sheet,
    }


class Searcher:
    """The search for one arm of one question: snapshot in replay, the real search (then saved) in record."""

    def __init__(
        self, store: lib.SnapshotStore, mode: str, company: str | None, company_id: int | None
    ):
        self.store = store
        self.mode = mode
        self.company = company
        self.company_id = company_id
        self.latency_ms = 0  # recorded latency of every search this arm made

    async def __call__(
        self, query: str, _company_id: int | None, top_k: int
    ) -> list[RetrievedChunk]:
        key = lib.snapshot_key(query, self.company, top_k, MODE_OF_SEARCH)
        entry = self.store.get(key)
        if entry is None:
            if self.mode == "replay":
                raise lib.ReplayMiss(f"no recorded search for {query!r} (key {key[:12]})")
            import time

            from app.rag.retrieve import retrieve_relevant_chunks

            started = time.monotonic()
            chunks = await retrieve_relevant_chunks(query, self.company_id, top_k)
            entry = {
                "query": query,
                "company": self.company,
                "top_k": top_k,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "results": [_row(c) for c in chunks],
            }
            self.store.put(key, entry)
        self.latency_ms += int(entry["latency_ms"])
        return [_chunk(r) for r in entry["results"]]


# ---- model calls --------------------------------------------------------------------------------
ROLES = {
    agentic.RELEVANCE_SYSTEM_PROMPT: "relevance",
    agentic.REWRITE_SYSTEM_PROMPT: "rewrite",
    agentic.GROUNDING_SYSTEM_PROMPT: "grounding",
}


class Checker:
    """The agentic layer's `llm` function, answered by the recorder; sums what it was asked for."""

    def __init__(self, recorder: lib.Recorder):
        self.recorder = recorder

    async def __call__(self, system: str, user: str) -> agentic.LlmReply:
        call = self.recorder.call(ROLES[system], system, user)
        return agentic.LlmReply(call.content, call.tokens_in, call.tokens_out, call.latency_ms)


def answer_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    """The user message POST /chat/rag builds: the guarded, wrapped, numbered sources, then the question."""
    safe = [replace(c, content=scan_and_neutralize(c.content).neutralized_text) for c in chunks]
    context = wrap_untrusted_context(build_context(safe))
    return f"Context:\n{context}\n\nQuestion: {scan_and_neutralize(question).neutralized_text}"


# ---- one arm of one question -------------------------------------------------------------------
async def run_arm(
    arm: str, case: dict, searcher: Searcher, recorder: lib.Recorder, checker: Checker
) -> lib.CaseResult:
    question = case["question"]
    relevant = set(case["relevant"])
    report = agentic.AgenticReport(enabled=True)
    if arm == "agentic":
        chunks, report = await agentic.retrieve_checked(
            question, None, DEFAULT_TOP_K, retrieve=searcher, llm=checker, enabled=True
        )
    else:
        chunks = await searcher(question, None, DEFAULT_TOP_K)
        report = agentic.AgenticReport(enabled=True)  # only used to run the grounding check below

    answer, answer_call = NONE_FOUND, None
    if chunks:
        answer_call = recorder.call(
            "answer", GROUNDED_SYSTEM_PROMPT, answer_prompt(question, chunks)
        )
        answer = answer_call.content
    grounding = await agentic.check_grounding(answer, chunks, report, checker)

    ranked = _dedupe([Path(c.source_path).name for c in chunks])
    cited = lib.cited_numbers(answer, len(chunks)) if chunks else []
    correct = sum(1 for n in cited if Path(chunks[n].source_path).name in relevant)
    metrics = {}
    if relevant:
        metrics = {
            "recall_at_1": lib.recall_at(ranked, relevant, 1),
            "recall_at_3": lib.recall_at(ranked, relevant, 3),
            "recall_at_4": lib.recall_at(ranked, relevant, 4),
            "mrr": lib.reciprocal_rank(ranked, relevant),
        }
    tokens_in = report.tokens_in + (answer_call.tokens_in if answer_call else 0)
    tokens_out = report.tokens_out + (answer_call.tokens_out if answer_call else 0)
    latency = (
        searcher.latency_ms + report.latency_ms + (answer_call.latency_ms if answer_call else 0)
    )
    calls = report.llm_calls + (1 if answer_call else 0)
    if arm == "plain":
        # the plain arm does not run the grounding check in production: measured, but not charged
        tokens_in -= report.tokens_in
        tokens_out -= report.tokens_out
        latency -= report.latency_ms
        calls -= report.llm_calls
        extra = 0
    else:
        extra = report.llm_calls
    return lib.CaseResult(
        id=case["id"],
        answerable=bool(relevant),
        ranked_docs=ranked,
        returned=len(chunks),
        answer=answer,
        declined=lib.declined(answer, bool(chunks)),
        grounded=None if grounding is None else grounding.grounded,
        citations_total=len(cited),
        citations_correct=correct,
        latency_ms=latency,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        llm_calls=calls,
        extra_calls=extra,
        rewritten=report.rewritten_query is not None,
        fell_back=report.fallback is not None,
        metrics=metrics,
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [i for i in items if not (i in seen or seen.add(i))]


async def run(mode: str) -> tuple[dict, dict]:
    cases = json.loads(GOLDEN.read_text())
    store = lib.SnapshotStore()
    recorder = lib.Recorder(mode=mode, api_key=os.environ.get("OPENROUTER_API_KEY", ""))
    checker = Checker(recorder)
    company_ids: dict[str, int] = {}
    if mode == "record":
        from app.db import get_pool
        from app.rag.retrieve import get_point_count

        if await get_point_count() == 0:
            raise SystemExit(
                "Qdrant has no documents: ingest the samples first (see the PR's How to try)."
            )
        pool = await get_pool()
        for name in {c["company"] for c in cases if c["company"]}:
            company_ids[name] = await pool.fetchval(
                "SELECT id FROM companies WHERE name = $1", name
            )
    results: dict[str, list[lib.CaseResult]] = {"plain": [], "agentic": []}
    for case in cases:
        for arm in ("plain", "agentic"):
            searcher = Searcher(
                store, mode, case["company"], company_ids.get(case["company"] or "")
            )
            results[arm].append(await run_arm(arm, case, searcher, recorder, checker))
    summaries = {arm: lib.summarise(rows) for arm, rows in results.items()}
    detail = {
        arm: [
            {
                "id": r.id,
                "ranked": r.ranked_docs,
                "returned": r.returned,
                "declined": r.declined,
                "grounded": r.grounded,
                "citations": [r.citations_correct, r.citations_total],
                "latency_ms": r.latency_ms,
                "extra_calls": r.extra_calls,
                "rewritten": r.rewritten,
                "answer": r.answer,
            }
            for r in rows
        ]
        for arm, rows in results.items()
    }
    return summaries, detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=("replay", "record"), default="replay")
    parser.add_argument(
        "--check", action="store_true", help="compare with baseline/agentic-v1.json"
    )
    parser.add_argument(
        "--save-baseline", action="store_true", help="write baseline/agentic-v1.json"
    )
    args = parser.parse_args(argv)
    if args.mode == "record":
        os.environ.setdefault("RETRIEVAL_MODE", MODE_OF_SEARCH)
    try:
        summaries, detail = asyncio.run(run(args.mode))
    except (lib.ReplayMiss, lib.RecordFailed) as exc:
        print(f"ERROR {exc}")
        return 2
    branch, sha = branch_and_sha()
    header = (
        f"agentic retrieval vs plain hybrid search  branch {branch} @ {sha}  [{args.mode}]\n"
        f"model {lib.MODEL}  version {lib.VERSION}  "
        f"(${lib.PRICE_IN_PER_M}/M in, ${lib.PRICE_OUT_PER_M}/M out)"
    )
    print(lib.format_table(summaries, header))
    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = RUNS / f"agentic-{stamp}-{sha}.json"
    out.write_text(json.dumps({"summaries": summaries, "cases": detail}, indent=1) + "\n")
    print(f"\nper-question detail: {out.relative_to(EVALS.parent)}")
    if args.save_baseline:
        BASELINE.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "date": datetime.now(UTC).strftime("%Y-%m-%d"),
                    "git_sha": sha,
                    "model": lib.MODEL,
                    "version": lib.VERSION,
                    "arms": summaries,
                },
                indent=2,
            )
            + "\n"
        )
        print(f"baseline written: {BASELINE.relative_to(EVALS.parent)}")
    if args.check and BASELINE.exists():
        problems = lib.compare(json.loads(BASELINE.read_text())["arms"], summaries)
        for problem in problems:
            print(f"REGRESSION {problem}")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
