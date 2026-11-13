"""Python-edition extension routes for knowledge bases (not part of the API contract shared with the Java
edition; see docs/python-extensions.md): list them, ingest an extra one, search one."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from app.rag.embeddings import EmbeddingsUnavailableError
from app.rag.knowledge_bases import (
    KnowledgeBase,
    all_knowledge_bases,
    count_knowledge_base_chunks,
    find_knowledge_base,
    ingest_knowledge_base,
    search_knowledge_base,
)
from app.routes.chat import _citation

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def known_knowledge_base(kb_id: str) -> KnowledgeBase:
    """A path parameter turned into the knowledge base it names, or a 404. Used with `Depends`, so each
    route below receives the object, not the string."""
    kb = find_knowledge_base(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f'No knowledge base named "{kb_id}".')
    return kb


class SearchRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    top_k: int = Field(default=4, ge=1, le=20, alias="topK")


@router.get("")
async def list_knowledge_bases():
    return [
        {
            "id": kb.id,
            "label": kb.label,
            "description": kb.description,
            "collection": kb.collection,
            "builtIn": kb.built_in,
            "chunks": await count_knowledge_base_chunks(kb),
        }
        for kb in all_knowledge_bases()
    ]


@router.post("/{kb_id}/ingest")
async def ingest(kb: Annotated[KnowledgeBase, Depends(known_knowledge_base)]):
    if kb.built_in:
        raise HTTPException(
            status_code=400,
            detail="The CRM documents are ingested with POST /api/v1/documents/ingest.",
        )
    summary = await ingest_knowledge_base(kb)
    return JSONResponse(
        status_code=200 if summary.status == "completed" else 502,
        content={
            "knowledgeBase": summary.knowledge_base,
            "documentsProcessed": summary.documents_processed,
            "chunksCreated": summary.chunks_created,
            "status": summary.status,
            "error": summary.error,
        },
    )


@router.post("/{kb_id}/search")
async def search(body: SearchRequest, kb: Annotated[KnowledgeBase, Depends(known_knowledge_base)]):
    try:
        chunks = await search_knowledge_base(kb, body.query, body.top_k)
    except EmbeddingsUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "knowledgeBase": kb.id,
        "results": [_citation(i, chunk) for i, chunk in enumerate(chunks)],
    }
