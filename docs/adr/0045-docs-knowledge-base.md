# 0045 — The project's own documentation as a knowledge base

- **Status:** Accepted (step 4 of the follow-up to the comparison lab; measured with an in-process Qdrant and a fake embedding model, **not asked a real question with a real model**)
- **Date:** 2026-11-28
- **Builds on:** [ADR 0029](0029-knowledge-bases.md) (knowledge bases) and [ADR 0044](0044-embedding-requests-and-ingestion-order.md) (embed before replace).

## Context

The `docs/` folder has 90 Markdown pages (about 890,000 characters). Finding the right one ("how do I run the application?", "how do I test the LangChain backends?") is slow, and pasting them all into a chat does not fit in any model's window. The knowledge-base machinery (E1: a second corpus in its own collection, a router that picks by description, cited answers) already does the job; three things stood in the way:

1. **The loader needs front matter.** Every document must carry a `title` and a `type` from a fixed list; the pages of `docs/` have neither, so ingestion would fail on the first file.
2. **The loader reads one folder level** (no subfolders), and `docs/` is organised in subfolders.
3. **Embedding quota.** All 90 pages are 1,810 chunks; the free Google embedding allowance has run out for us before (about 1,000 a day, and whether it counts requests or embeddings is **not verified**).

## Decision

1. **A new, off-by-default knowledge base `docs`.** `DOCS_KNOWLEDGE_BASE=true` (and, in Docker, `DOCS_DIR=/docs`, mounted read-only from `./docs`) adds it to the list; the default list (`crm`, `agri-supply`) and every existing test are unchanged. Collection `document_chunks_docs`.
2. **A reader for project pages (`app/rag/docs_reader.py`).** The title is the **first `#` heading** (the file name when a page has none); the type is fixed as `product`; front matter, if a page has any, is dropped; **one folder level at a time**, so the folders are named: `.` (the top of `docs/`, where the how-to guides live) and `stages` (the stage guides). **Left out on purpose:** `adr/` (good for "why did we choose X", a second pass if wanted), `v2-baseline/` (superseded: it would give stale answers), `concepts/`, `fe/`, `img/` and `diagrams/`. Measured on the real folder: **28 pages, 1,020 chunks** (592 top level, 428 stages), every page with a heading.
3. **Ingest a folder at a time.** `POST /api/v1/knowledge-bases/docs/ingest` rebuilds the whole knowledge base; `POST .../ingest?folder=stages` **adds or refreshes only that folder** (its old chunks are deleted by file, the rest of the collection stays, nothing is duplicated), so the 1,020 chunks can be spread over days. A folder that is not configured, or on a knowledge base that has none, is a 422 that lists the choices. Every page keeps the **same document number** whichever way it is ingested (its position among all configured pages).
4. **Embed first, replace after** (ADR 0044), including the one-folder mode: a failed embedding call leaves the knowledge base as it was.
5. **A style hint for the answer.** A knowledge base can carry a one-line `answer_hint`; when chunks of it supply the answer (`route` and `all` strategies of `POST /api/v1/chat/multi`), the line is added to the question prompt: for `docs` it asks to quote commands, file names and settings exactly as written, each command in a code block, and to name the page. The hint is written in our code, never read from a document. (The `agent` strategy has its own prompt and does not use it.)
6. **The description is the routing.** The router reads it to decide whether to search `docs`: it names starting the stack, ingesting, the smoke test, the runbook, testing and troubleshooting, the API reference, the architecture, the stage guides and the comparison lab, so "how do I run it" and "how do I test the LangChain backends" go there and customer questions do not.

## Consequences

- **Cost to turn on:** set `DOCS_KNOWLEDGE_BASE=true`, `docker compose up -d --force-recreate api-py`, then ingest `.` and `stages` (on one day or two). About 1,020 embeddings: possibly more than a day's free allowance if the allowance counts embeddings, hence the folder-at-a-time mode.
- **Staleness:** the pages change with the code; the knowledge base does not follow by itself. Re-ingest a folder after editing it (the folder mode makes that cheap). The pages say "step N" and "PR #x": answers may repeat things that have since changed, which is why `v2-baseline/` is out.
- **The heading-aware chunker is not built.** Chunks are the usual 600 characters with 100 overlap, so a long table or command block can be split across two chunks. Whether answers come out in pieces is **not measured** (no real question was asked); if they do, a heading-aware chunker for this knowledge base is the next step.
- **No web-app selector.** The Python web app has no multi-source mode; use `POST /api/v1/chat/multi` (strategy `route`) or the knowledge base's own `/search`.
- **A question can reach private pages only if they are in `docs/`.** Nothing outside the two configured folders is read, and the mount is read-only.

## How this was checked

`tests/test_docs_knowledge_base.py` (14 tests, no key, in-process Qdrant): the title and type rules and the front-matter drop; one folder level only; the setting off by default and on with the right collection, folders and description; the top level and `stages` ingested while an ADR and a V2 page are not found; ingesting twice never duplicates; one folder refreshed alone keeps the rest, embeds only its own pages and replaces the old text; either folder can come first; document numbers are stable; an unknown folder and a folder on another knowledge base are 422; a failed embedding call leaves both modes untouched; a missing folder is reported in the summary; the answer hint appears only for the knowledge base that supplied a chunk. A dry run on the real `docs/` gave the 28 pages and 1,020 chunks above.
