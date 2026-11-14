"""Stage 5.5, seam 2: dense retrieval, written with LangChain's Qdrant vector store.

Replaces only the part of `app.rag.retrieve` that talks to Qdrant for a dense search: embedding the question,
the nearest-neighbour query, and turning the hits into `RetrievedChunk`s. Everything around it stays ours
(the index-model check, the company filter, the exact-versus-HNSW choice, the reranker, the similarity floor
value, the response shape), so both sides can be compared on the same questions.

Things the framework needs or does that our code does not (ADR 0027):
- it reads a chunk's fields from a nested `metadata` payload key, so ingestion writes that extra copy when
  `RETRIEVAL_IMPL=frameworks` (`app.rag.ingest`); an index built without it returns chunks with no title;
- it embeds the question itself through an `Embeddings` object, so our async Gemini call is wrapped in a
  small adapter that is called from the store's worker thread;
- built with its defaults it embeds a dummy text and reads the collection's configuration once, when it
  is constructed: a hidden model call, made here from inside the event loop, where the adapter below
  cannot run it. Switched off (below), a search is one Qdrant call, the same as ours (measured);
- its retriever interface (`as_retriever(search_type="similarity_score_threshold")`) rescales cosine
  scores to `(1 + cosine) / 2`, which would silently turn our similarity floor into "keep nearly everything";
  so this module calls the store's raw-score search with `score_threshold` instead.
"""

from __future__ import annotations

import asyncio
import functools

from qdrant_client import QdrantClient

from app.config import get_settings
from app.frameworks import require
from app.rag.embeddings import embed_text, embed_texts
from app.rag.qdrant_store import DENSE, collection_name
from app.rag.retrieve import (
    MIN_SIMILARITY,
    RetrievedChunk,
    _company_filter,
    choose_search_strategy,
    get_point_count,
)


@functools.cache
def _embeddings_class():
    """LangChain's `Embeddings` interface over our own embedding functions (so the model, the key and
    the tracing stay ours). The store calls it from a worker thread, so it hands the async call back to
    the event loop that is running the request."""
    base = require("langchain_core.embeddings").Embeddings

    class OurEmbeddings(base):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            self.loop: asyncio.AbstractEventLoop | None = None

        def _run(self, coroutine):
            if self.loop is None:
                return asyncio.run(coroutine)
            return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result()

        def embed_query(self, text: str) -> list[float]:
            return self._run(embed_text(text))

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return self._run(embed_texts(texts))

        async def aembed_query(self, text: str) -> list[float]:
            return await embed_text(text)

    return OurEmbeddings


@functools.cache
def _store(url: str, collection: str):
    """The LangChain vector store over our collection and its named `dense` vector, built once."""
    module = require("langchain_qdrant")
    embeddings = _embeddings_class()()
    store = module.QdrantVectorStore(
        client=QdrantClient(url=url),
        collection_name=collection,
        embedding=embeddings,
        retrieval_mode=module.RetrievalMode.DENSE,
        vector_name=DENSE,
        content_payload_key="content",
        metadata_payload_key="metadata",
        # Both default to True and make the constructor embed a dummy text (a model call, from inside the
        # event loop) and read the collection's configuration. Off here (ADR 0027).
        validate_embeddings=False,
        validate_collection_config=False,
    )
    return store, embeddings


def _chunk(document, score: float) -> RetrievedChunk:
    metadata = document.metadata
    return RetrievedChunk(
        chunk_id=metadata["_id"],
        document_id=metadata["document_id"],
        document_title=metadata["document_title"],
        source_path=metadata["source_path"],
        doc_type=metadata["doc_type"],
        company_name=metadata.get("company_name"),
        chunk_index=metadata["chunk_index"],
        content=document.page_content,
        similarity=score,
        page=metadata.get("page"),
        sheet=metadata.get("sheet"),
    )


async def dense_chunks(question: str, company_id: int | None, limit: int) -> list[RetrievedChunk]:
    """The `limit` chunks closest in meaning to the question, best first, at or above the similarity
    floor, optionally only this company's and the company-agnostic ones."""
    settings = get_settings()
    store, embeddings = _store(settings.qdrant_url, collection_name())
    embeddings.loop = asyncio.get_running_loop()
    _strategy, search_params = choose_search_strategy(await get_point_count())
    hits = await asyncio.to_thread(
        store.similarity_search_with_score,
        question,
        k=limit,
        filter=_company_filter(company_id),
        search_params=search_params,
        score_threshold=MIN_SIMILARITY,
    )
    return [_chunk(document, score) for document, score in hits]
