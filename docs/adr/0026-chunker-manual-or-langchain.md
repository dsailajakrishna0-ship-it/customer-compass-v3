# 0026 — The chunker: our fixed windows or LangChain's recursive text splitter

- **Status:** Accepted: **manual stays the default**; the framework side ships as `CHUNKER_IMPL=frameworks`
- **Date:** 2026-11-13
- **Roadmap sub-stage:** 5.5 (seam 1 of 3)

## Context

Ingestion cuts every document segment into chunks with `chunk_text` (ADR 0003's policy, ported from the Express app): 600-character windows with 100 characters of overlap. It is 24 lines of code and cuts wherever the count falls, so it sometimes cuts a word in two. LangChain's `RecursiveCharacterTextSplitter` (in the small `langchain-text-splitters` package, 1.1.3 checked on PyPI on 2026-11-13) cuts at the largest separator that keeps a piece under the size: blank line, then line break, then space. The roadmap asks whether it should replace our code.

## Decision

1. **`CHUNKER_IMPL=manual|frameworks`, default `manual`.** `chunk_text` keeps its signature (`text, chunk_size, overlap -> list[Chunk]`) and dispatches; `app/frameworks/chunker.py` is the LangChain side. It returns the same `Chunk` type with the same validation errors, the same empty-text rule and character offsets from the splitter's `add_start_index`, so ingestion, the page and sheet citations, and the tests cannot tell the sides apart.
2. **The packages are an optional install** (`evals/requirements-frameworks.txt`, pinned, kept out of `uv.lock`); a missing package gives one error saying how to install it.
3. **Measure only the chunker.** The 19 sample documents are cut both ways, embedded with `gemini-embedding-001`, and the 42 retrieval questions are ranked by cosine similarity in memory, so nothing but the chunking differs (`just eval-frameworks`, replayed from `evals/frameworks/chunker.json`).

## Results

| | manual | frameworks |
| --- | --- | --- |
| chunks from the 19 documents | 33 | 34 |
| median chunk size (characters) | 476 | 393 |
| chunks cut in the middle of a word | 6 | 0 |
| recall@1 | 0.843 | 0.843 |
| recall@3 | 0.972 | 1.000 |
| recall@5 | 0.986 | 1.000 |
| MRR | 1.000 | 1.000 |
| lines of code this side adds | 24 | 32 |

What the numbers say:

- **Cleaner cuts.** The splitter never cut a word in two; our windows did on 6 of 33 chunks. That is the clearest, most certain difference.
- **Recall is equal or better, by one question.** recall@3 and recall@5 are higher because one two-document question found its second document within three results instead of four or five. That is 1 of 36 answerable questions, on a corpus of 33 chunks: a hint, not proof.
- **More code, not less.** To keep our contract (validation, empty text, offsets into the trimmed text) the wrapper is 32 lines against 24. The framework did not remove code here; it replaced the cutting logic with a call.
- **One more chunk and smaller chunks.** Cutting at separators gives a median 393 characters instead of 476, so the same text is spread over a few more, shorter chunks.

## Decision on shipping

**Keep `manual` as the default and ship the framework side as an option.** The numbers do not make it worse, and they lean slightly its way, but the two reasons not to switch are stronger: (1) the **Java edition's chunk counts are equal to ours file by file** (19 documents, 33 chunks; [port status](../port-status.md)), and changing the default here changes the contract the Java edition ports, so both editions would have to move together; (2) the quality gain is one question on a tiny corpus.

**What would make us look again:** a larger corpus where the golden set shows the splitter ahead by more than one question, and the Java edition's LangChain4j splitter (or Spring AI's) measured the same way. Then the default changes in both editions in one step, with a re-ingest.

## Alternatives considered

- **`MarkdownHeaderTextSplitter` or a token-based splitter.** Better for some documents, but they change what a chunk is more than the recursive splitter does and would need their own comparison; our corpus is mostly short Markdown with PDF, Word and Excel segments already cut by page or sheet.
- **A semantic chunker** (cut where the meaning shifts, by comparing embeddings): needs embedding calls at ingestion and is a technique of its own; it belongs in the RAG variants guide.

## Consequences

- With the setting on, ingestion makes slightly more, smaller chunks; re-ingest after changing it (the index is rebuilt from scratch anyway).
- `app/frameworks/chunker.py` and its tests (`tests/test_frameworks.py`) run in CI through `just test-frameworks`.
