"""Knowledge bases: more than one corpus, each in its own Qdrant collection (a Python-edition extension,
ADR 0029; not part of the API contract shared with the Java edition).

The CRM documents are the knowledge base `crm`: the configured collection, ingested by
`POST /documents/ingest`, exactly as before. Every extra knowledge base (setting `KNOWLEDGE_BASES`) has
a collection of its own, `<QDRANT_COLLECTION>_<id with dashes as underscores>`, plus its own keyword
vectors, and is ingested by `ingest_knowledge_base` below, which never touches the CRM collection, the
`documents` table or the ingestion runs.

Searching a knowledge base is the ordinary retrieval code (`retrieve_relevant_chunks`) run inside
`using_collection(...)`: hybrid search, the similarity floor and the optional reranker therefore apply
to every knowledge base with no second implementation, and a search can only ever see its own corpus.
"""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from qdrant_client.models import PointStruct

from app.config import get_settings
from app.rag.embeddings import embed_texts
from app.rag.ingest import _with_framework_metadata, chunk_segments, load_documents
from app.rag.qdrant_store import (
    DENSE,
    SPARSE,
    collection_name,
    count_chunks,
    get_client,
    recreate_collection,
    upsert_chunks,
    using_collection,
)
from app.rag.retrieve import RetrievedChunk, retrieve_relevant_chunks
from app.rag.sparse import document_vector

logger = logging.getLogger("app.rag.knowledge_bases")

CRM = "crm"


@dataclass(frozen=True)
class KnowledgeBase:
    id: str
    label: str
    description: str
    collection: str
    built_in: bool
    source_dir: Path | None = None  # extra knowledge bases only; None: the default folder


@dataclass
class KnowledgeBaseIngestSummary:
    knowledge_base: str
    documents_processed: int
    chunks_created: int
    status: str
    error: str | None = None


def _collection_for(kb_id: str) -> str:
    return f"{get_settings().qdrant_collection}_{kb_id.replace('-', '_')}"


def all_knowledge_bases() -> list[KnowledgeBase]:
    """The built-in `crm` knowledge base first, then each configured extra one."""
    settings = get_settings()
    crm = KnowledgeBase(
        id=CRM,
        label="CRM documents",
        description=(
            "Customer emails, call and meeting notes, support tickets, contracts and product "
            "overviews for the CRM's customers."
        ),
        collection=settings.qdrant_collection,
        built_in=True,
    )
    extras = [
        KnowledgeBase(
            id=source.id,
            label=source.label,
            description=source.description,
            collection=_collection_for(source.id),
            built_in=False,
            source_dir=source.source_dir,
        )
        for source in settings.knowledge_bases
    ]
    return [crm, *extras]


def find_knowledge_base(kb_id: str) -> KnowledgeBase | None:
    return next((kb for kb in all_knowledge_bases() if kb.id == kb_id), None)


def _hint(kb: KnowledgeBase) -> str:
    """Where a person is sent when this knowledge base was built with another embedding model."""
    if kb.built_in:  # the CRM documents keep their own ingest route
        return "Click Ingest documents (or POST /api/v1/documents/ingest)"
    return f"Re-ingest this knowledge base (POST /api/v1/knowledge-bases/{kb.id}/ingest)"


def _source_dir(kb: KnowledgeBase) -> tuple[Path, Path]:
    """The folder of an extra knowledge base's documents, and the root `source_path` is relative to."""
    if kb.source_dir is not None:
        return kb.source_dir, kb.source_dir.parent
    override = get_settings().sample_data_dir
    # Local dev: apps/api-py/app/rag/knowledge_bases.py -> repo root -> sample-data. In Docker,
    # SAMPLE_DATA_DIR (/sample-data/documents) says where sample-data is mounted.
    sample_data = (
        override.parent if override else Path(__file__).resolve().parents[4] / "sample-data"
    )
    return sample_data / "knowledge-bases" / kb.id, sample_data.parent


async def count_knowledge_base_chunks(kb: KnowledgeBase) -> int:
    """How many chunks are stored; 0 before the first ingestion or when Qdrant cannot be reached."""
    try:
        with using_collection(kb.collection):
            if not await get_client().collection_exists(collection_name()):
                return 0
            return await count_chunks()
    except Exception as exc:  # noqa: BLE001 - the list still answers when Qdrant is down
        logger.warning("kb_count_failed kb=%s error=%s", kb.id, type(exc).__name__)
        return 0


async def ingest_knowledge_base(kb: KnowledgeBase) -> KnowledgeBaseIngestSummary:
    """Rebuilds an extra knowledge base from its folder: same parser, chunker and embeddings as the CRM
    documents, each chunk stored with its keyword vector. Running it twice never duplicates."""
    documents_processed = chunks_created = 0
    try:
        folder, root = _source_dir(kb)
        if not folder.is_dir():
            raise FileNotFoundError(
                f"Could not find the folder of knowledge base {kb.id}: {folder}. Set its source_dir."
            )
        documents = load_documents(folder, root)
        with using_collection(kb.collection, _hint(kb)):
            await recreate_collection()
            for document_id, doc in enumerate(documents, start=1):
                chunks = chunk_segments(doc.segments)
                if not chunks:
                    continue
                embeddings = await embed_texts([chunk.content for _segment, chunk in chunks])
                points = [
                    PointStruct(
                        id=str(uuid.uuid4()),
                        vector={DENSE: embeddings[i], SPARSE: document_vector(chunk.content)},
                        payload=_with_framework_metadata(
                            {
                                **({"page": segment.page} if segment.page is not None else {}),
                                **({"sheet": segment.sheet} if segment.sheet is not None else {}),
                                "knowledge_base": kb.id,
                                "document_id": document_id,
                                "chunk_index": chunk.index,
                                "content": chunk.content,
                                "char_start": chunk.char_start,
                                "char_end": chunk.char_end,
                                "document_title": doc.title,
                                "source_path": doc.source_path,
                                "doc_type": doc.doc_type,
                                # a corpus about no one customer: eligible for every scoped search
                                "company_id": None,
                                "company_name": None,
                            }
                        ),
                    )
                    for i, (segment, chunk) in enumerate(chunks)
                ]
                await upsert_chunks(points)
                chunks_created += len(points)
                documents_processed += 1
        return KnowledgeBaseIngestSummary(kb.id, documents_processed, chunks_created, "completed")
    except Exception as exc:  # noqa: BLE001 - reported in the summary, like the CRM ingestion
        logger.warning("kb_ingest_failed kb=%s error=%s", kb.id, type(exc).__name__)
        return KnowledgeBaseIngestSummary(
            kb.id, documents_processed, chunks_created, "failed", str(exc) or type(exc).__name__
        )


async def search_knowledge_base(
    kb: KnowledgeBase, query: str, top_k: int = 4
) -> list[RetrievedChunk]:
    """The ordinary retrieval, aimed at one knowledge base's collection. Before the first ingestion
    there is no collection and so nothing to find (an empty list, not an error)."""
    with using_collection(kb.collection, _hint(kb)):
        if not await get_client().collection_exists(collection_name()):
            return []
        return await retrieve_relevant_chunks(query, top_k=top_k)
