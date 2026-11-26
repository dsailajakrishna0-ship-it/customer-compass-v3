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
from app.rag import docs_reader
from app.rag.embeddings import embed_texts
from app.rag.ingest import ParsedDocument, _with_framework_metadata, chunk_segments, load_documents
from app.rag.qdrant_store import (
    DENSE,
    SPARSE,
    collection_exists,
    collection_name,
    count_chunks,
    delete_chunks_for_sources,
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
    reader: str = (
        "documents"  # "documents" (front matter, PDF, Word, Excel) or "docs" (project pages)
    )
    folders: tuple[
        str, ...
    ] = ()  # reader "docs" only: the folders read, "." being source_dir itself
    answer_hint: str | None = (
        None  # a line added to the answer prompt when this knowledge base is used
    )


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
            reader=source.reader,
            folders=tuple(source.folders or ()),
        )
        for source in settings.knowledge_bases
    ]
    if settings.docs_knowledge_base:
        extras.append(_docs_knowledge_base())
    return [crm, *extras]


DOCS = "docs"
DOCS_FOLDERS = (docs_reader.TOP_LEVEL, "stages")


def _docs_knowledge_base() -> KnowledgeBase:
    """The project's own documentation (step 4, ADR 0045): the guides at the top of `docs/` (how to run,
    test and troubleshoot) and the stage guides. The superseded V2 pages and the ADRs are left out."""
    settings = get_settings()
    source_dir = settings.docs_dir or Path(__file__).resolve().parents[4] / "docs"
    return KnowledgeBase(
        id=DOCS,
        label="Project documentation",
        description=(
            "How Customer Compass works and how to run it: starting the stack, ingesting documents, the "
            "smoke test and acceptance runbook, the testing and troubleshooting guides, the API reference, "
            "the architecture and tech stack, the stage guides, and the comparison lab (LangChain, "
            "LangGraph, the multi-agent patterns) with its hand-test script."
        ),
        collection=_collection_for(DOCS),
        built_in=False,
        source_dir=source_dir,
        reader="docs",
        folders=DOCS_FOLDERS,
        answer_hint=(
            "This answer comes from the project's own documentation. Quote commands, file names and "
            "settings exactly as written in the context, each command in a code block, and say which page "
            "each one comes from."
        ),
    )


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


def _numbered_documents(
    kb: KnowledgeBase, source_dir: Path, root: Path, folder: str | None
) -> list[tuple[int, ParsedDocument]]:
    """The documents to ingest, each with its document number. For the project pages the number is the
    page's position among ALL configured pages, so it does not change when one folder is ingested alone."""
    if kb.reader == "docs":
        every = docs_reader.all_paths(source_dir, kb.folders)
        wanted = every if folder is None else docs_reader.folder_paths(source_dir, folder)
        wanted_set = set(wanted)
        return [
            (number, docs_reader.read_page(path, root))
            for number, path in enumerate(every, start=1)
            if path in wanted_set
        ]
    if folder is not None:
        raise ValueError(f"The knowledge base {kb.id} has no folders to choose from.")
    if not source_dir.is_dir():
        raise FileNotFoundError(
            f"Could not find the folder of knowledge base {kb.id}: {source_dir}. Set its source_dir."
        )
    return list(enumerate(load_documents(source_dir, root), start=1))


async def ingest_knowledge_base(
    kb: KnowledgeBase, folder: str | None = None
) -> KnowledgeBaseIngestSummary:
    """Rebuilds an extra knowledge base from its folder: same chunker and embeddings as the CRM documents,
    each chunk stored with its keyword vector. Running it twice never duplicates.

    For the project pages a single `folder` can be ingested alone (to spread the embedding calls over
    several days): that folder's pages are added or refreshed and the rest of the collection stays."""
    documents_processed = chunks_created = 0
    try:
        source_dir, root = _source_dir(kb)
        numbered = _numbered_documents(kb, source_dir, root, folder)
        # Read-only phase first: embed every chunk BEFORE the collection is touched, so a failed
        # embedding call leaves the previous knowledge base as it was.
        prepared = [(number, doc, chunk_segments(doc.segments)) for number, doc in numbered]
        vectors = await embed_texts(
            [chunk.content for _number, _doc, chunks in prepared for _segment, chunk in chunks]
        )
        with using_collection(kb.collection, _hint(kb)):
            if folder is None or not await collection_exists():
                await recreate_collection()
            else:
                await delete_chunks_for_sources([doc.source_path for _number, doc, _c in prepared])
            offset = 0
            for document_id, doc, chunks in prepared:
                if not chunks:
                    continue
                embeddings = vectors[offset : offset + len(chunks)]
                offset += len(chunks)
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
