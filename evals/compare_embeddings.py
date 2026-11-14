"""Compares embedding models on the golden retrieval set (Stage 4.3, ADR 0021).

For each model it embeds every chunk of the sample documents and every golden question, ranks the
documents by the best-matching chunk, and reports recall@1/3/5 and MRR (the same scoring as
`run_eval.py`). It needs no database and no Qdrant: ranking is done in memory, so the only thing that
differs between the rows is the embedding model.

    uv run --project apps/api-py python evals/compare_embeddings.py                # google and fastembed
    uv run --project apps/api-py --extra local-embeddings python evals/compare_embeddings.py --models fastembed
    uv run --project apps/api-py python evals/compare_embeddings.py --models google --out evals/baseline/embeddings.json

`google` needs GOOGLE_API_KEY and the internet. `fastembed` needs the optional extra
(`uv sync --extra local-embeddings` in apps/api-py) and downloads a small model on first use.

Besides the ranking scores it prints the *similarity gap*: the lowest best-match score of an
answerable question, against the highest best-match score of an unanswerable one. A positive gap
means a similarity floor can separate them; the floor itself (0.60 for Gemini on the CRM documents) does not carry over
from one model to another.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS))  # metrics.py
sys.path.insert(0, str(EVALS.parent / "apps" / "api-py"))  # the app package
import metrics  # noqa: E402

GOLDEN = EVALS / "golden" / "retrieval.json"


def rank_documents(
    question_vector: list[float],
    chunk_vectors: list[list[float]],
    chunk_documents: list[str],
    cosine,
) -> tuple[list[str], float]:
    """Documents best first (a document counts once, at its best chunk) and the best score."""
    best: dict[str, float] = {}
    for vector, document in zip(chunk_vectors, chunk_documents, strict=True):
        score = cosine(question_vector, vector)
        if score > best.get(document, float("-inf")):
            best[document] = score
    ranked = sorted(best, key=lambda d: best[d], reverse=True)
    return ranked, best[ranked[0]] if ranked else 0.0


def summarise(cases: list[dict]) -> dict:
    answerable = [c for c in cases if c["relevant"]]
    unanswerable = [c for c in cases if not c["relevant"]]
    lowest = min((c["top_score"] for c in answerable), default=0.0)
    highest = max((c["top_score"] for c in unanswerable), default=0.0)
    return {
        "cases": len(cases),
        "recall_at_1": metrics.mean(
            [metrics.recall_at_k(c["ranked"], set(c["relevant"]), 1) for c in answerable]
        ),
        "recall_at_3": metrics.mean(
            [metrics.recall_at_k(c["ranked"], set(c["relevant"]), 3) for c in answerable]
        ),
        "recall_at_5": metrics.mean(
            [metrics.recall_at_k(c["ranked"], set(c["relevant"]), 5) for c in answerable]
        ),
        "mrr": metrics.mean(
            [metrics.reciprocal_rank(c["ranked"], set(c["relevant"])) for c in answerable]
        ),
        "lowest_answerable_top_score": round(lowest, 4),
        "highest_unanswerable_top_score": round(highest, 4),
        "similarity_gap": round(lowest - highest, 4),
    }


async def evaluate(provider: str) -> dict:
    from app.rag.embeddings import embed_documents, embed_query, embedding_model_id
    from app.rag.ingest import _load_documents, chunk_segments
    from app.rag.retrieve import cosine

    chunks: list[tuple[str, str | None, str]] = []  # (document name, company, text)
    for document in _load_documents():
        for _segment, chunk in chunk_segments(document.segments):
            chunks.append((Path(document.source_path).name, document.company_name, chunk.content))

    started = time.monotonic()
    vectors = await embed_documents([text for _name, _company, text in chunks], provider)
    corpus_seconds = time.monotonic() - started

    cases = []
    query_seconds = 0.0
    for case in json.loads(GOLDEN.read_text()):
        started = time.monotonic()
        question_vector = await embed_query(case["question"], provider)
        query_seconds += time.monotonic() - started
        # a company-scoped question only sees that company's chunks and company-agnostic ones
        eligible = [
            i
            for i, (_n, company, _t) in enumerate(chunks)
            if not case["company"] or company in (None, case["company"])
        ]
        ranked, top = rank_documents(
            question_vector,
            [vectors[i] for i in eligible],
            [chunks[i][0] for i in eligible],
            cosine,
        )
        cases.append(
            {"id": case["id"], "relevant": case["relevant"], "ranked": ranked, "top_score": top}
        )

    return {
        "model": embedding_model_id(provider),
        "dimensions": len(vectors[0]) if vectors else 0,
        "chunks": len(chunks),
        "seconds_to_embed_corpus": round(corpus_seconds, 2),
        "ms_per_question": round(1000 * query_seconds / max(1, len(cases)), 1),
        "metrics": summarise(cases),
        "cases": cases,
    }


def print_table(results: list[dict]) -> None:
    rows = [
        ("model", lambda r: r["model"]),
        ("dimensions", lambda r: r["dimensions"]),
        ("chunks", lambda r: r["chunks"]),
        ("recall@1", lambda r: f"{r['metrics']['recall_at_1']:.3f}"),
        ("recall@3", lambda r: f"{r['metrics']['recall_at_3']:.3f}"),
        ("recall@5", lambda r: f"{r['metrics']['recall_at_5']:.3f}"),
        ("MRR", lambda r: f"{r['metrics']['mrr']:.3f}"),
        ("lowest answerable top score", lambda r: r["metrics"]["lowest_answerable_top_score"]),
        (
            "highest unanswerable top score",
            lambda r: r["metrics"]["highest_unanswerable_top_score"],
        ),
        ("similarity gap", lambda r: r["metrics"]["similarity_gap"]),
        ("seconds to embed corpus", lambda r: r["seconds_to_embed_corpus"]),
        ("ms per question", lambda r: r["ms_per_question"]),
    ]
    width = max(len(name) for name, _ in rows)
    for name, get in rows:
        print(f"{name:<{width}}  " + "  ".join(f"{get(r)!s:<34}" for r in results))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--models", nargs="+", choices=("google", "fastembed"), default=["google", "fastembed"]
    )
    parser.add_argument("--out", help="write the full report to this JSON file")
    args = parser.parse_args()
    results = [asyncio.run(evaluate(provider)) for provider in args.models]
    print_table(results)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2) + "\n")
        print(f"\nreport written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
