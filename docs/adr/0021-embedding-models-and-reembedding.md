# 0021 — Choosing the embedding model, and re-embedding when it changes

- **Status:** Accepted (default unchanged; see "What is still open")
- **Date:** 2026-11-07
- **Roadmap sub-stage:** 4.3

## Context

Search quality starts with the 🟪embedding model: it decides which chunks look similar. V3 uses Google's hosted `gemini-embedding-001` (768 numbers per chunk, a free-tier key). 4.3 asks two questions: is a small open-source model good enough to be an alternative, and what happens to the stored vectors when the model changes?

Vectors from two models cannot be compared, and they can even have different lengths (384 against 768). Before this stage nothing recorded which model made the vectors in the index, so changing the model setting would have given wrong results or a confusing Qdrant error.

## Decision

1. **An `EMBEDDING_PROVIDER` setting** chooses `google` (default) or `fastembed`. The rest of the app calls `embed_documents` and `embed_query`; the provider is the only thing that differs. Models such as bge expect a short instruction in front of a *question* but not in front of a *document*, so the two entry points are separate (`query_embed` and `embed` in FastEmbed).
2. **FastEmbed is an optional install**, not part of the API image: `uv sync --extra local-embeddings` in `apps/api-py`. Its default model is `BAAI/bge-small-en-v1.5` (MIT licence, 384 numbers, about 67 MB, runs on the CPU through ONNX, no PyTorch). This is a *comparison*, and "never adopted by default" as the roadmap says, so [ADR 0010](0010-cloud-only-models.md) (no local chat model) still holds.
3. **The index records its model.** The collection stores `embedding_model` (for example `google:gemini-embedding-001`) in its metadata, and the vector size comes from the provider. Every search first checks that the configured model equals the recorded one (cached for 60 seconds); if not, it fails with a message saying to click **Ingest documents** (a 503 through the existing embeddings error path). An index with no recorded model, made before 4.3, is not checked. Every ingestion run also stores the model name in `ingestion_runs`.
4. **Re-embedding is "ingest again".** Ingestion already rebuilds the whole collection, so changing the model needs no migration, only one ingest.
5. **A comparison script** (`evals/compare_embeddings.py`) embeds the corpus and the golden questions with each model and ranks in memory, so only the model differs. It needs no database or Qdrant.

## Results

Measured 2026-11-07 on the 19 sample files (33 chunks) and the 42-question golden set (36 answerable, 6 unanswerable):

| | `fastembed:BAAI/bge-small-en-v1.5` | `google:gemini-embedding-001` |
| --- | --- | --- |
| Numbers per chunk | 384 | 768 |
| recall@1 / @3 / @5 | 0.787 / 0.986 / 1.000 | *run `--models google` (needs your key)* |
| MRR | 0.972 | *same* |
| Embed the corpus (33 chunks) | 14 s on this laptop's CPU, once | *a network call per chunk* |
| One question | about 15 ms | *a network call* |
| Lowest answerable best-match score | 0.64 | *same* |
| Highest unanswerable best-match score | 0.77 | *same* |
| Similarity gap (positive means a floor can separate them) | **-0.12** | *same* |

For orientation, the V2-seed baseline for Gemini (16 Markdown files, 28 chunks, an older corpus, so only indicative) was recall@1 0.84, @3 0.99, @5 0.99 and MRR 1.00, with 0 of 6 unanswerable questions declined by the 0.45 floor.

## What is still open

- **The Gemini row on the same corpus.** It needs `GOOGLE_API_KEY` and the internet (`uv run --project apps/api-py python evals/compare_embeddings.py --models google`). Until it is filled, "almost as good" is a reading of two different corpora, not a measurement.
- **The similarity floor does not carry across models.** `MIN_SIMILARITY` is 0.45, tuned for Gemini. For bge-small even *unrelated* questions score 0.64 to 0.77, so the same floor would let everything through (the gap above is negative). Changing the model therefore also means re-tuning the floor, which is another reason the default does not change in this PR. Gemini's own gap may also be small or negative on this corpus; the run will show it.

## Alternatives considered

- **Make FastEmbed the default.** Free, offline and fast, but the unmeasured Gemini row and the floor above make that premature, and an ONNX model in the image is a new thing to ship and scan.
- **Store the model name in Postgres instead of Qdrant.** Possible (`ingestion_runs` has it), but the truth about the vectors is the collection, and the check then needs no database call.
- **Re-embed automatically when the model changes.** It would hide a slow, possibly paid operation behind a search request. A clear error and one explicit ingest is safer.
- **Larger local models** (for example `bge-base`, `nomic-embed`). Better quality, bigger downloads; the setting `FASTEMBED_MODEL` allows them without code changes.

## Consequences

- Changing `EMBEDDING_PROVIDER` or `FASTEMBED_MODEL` requires one ingest; until then searches return the re-ingest message.
- Chunk vectors and the collection size depend on the provider, so `just eval-retrieval` and the saved baseline are only comparable for the same model.
- `ingestion_runs.embedding_model` now holds `provider:model` for new runs (older rows hold the bare Google model name).
