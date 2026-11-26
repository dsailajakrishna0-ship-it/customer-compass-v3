"""Ingestion embeds everything BEFORE it replaces anything (no key, no database, no Qdrant): a failed
embedding call leaves the previous index as it was, for the CRM documents and for a knowledge base."""

import pytest

from app.rag import ingest, knowledge_bases
from app.rag.embeddings import EmbeddingsUnavailableError
from app.rag.ingest import ParsedDocument
from app.rag.parse import Segment


class Recorder:
    def __init__(self):
        self.events: list[str] = []


class FakePool:
    def __init__(self, rec: Recorder):
        self.rec = rec

    async def fetchrow(self, query, *args):
        if "INSERT INTO ingestion_runs" in query:
            return {"id": 1}
        if "INSERT INTO documents" in query:
            return {"id": 7}
        return None  # no company row: the document is not linked to a company

    async def execute(self, query, *args):
        self.rec.events.append("truncate" if "TRUNCATE" in query else "update-run")


def documents():
    text = "First paragraph of a note.\n\nSecond paragraph of a note."
    return [
        ParsedDocument("a.md", "A", "note", None, [Segment(text=text)]),
        ParsedDocument("b.md", "B", "note", None, [Segment(text=text)]),
    ]


@pytest.fixture
def rec(monkeypatch):
    recorder = Recorder()

    async def get_pool():
        return FakePool(recorder)

    async def recreate_collection():
        recorder.events.append("recreate")

    async def upsert_chunks(points):
        recorder.events.append(f"upsert:{len(points)}")

    async def embed_texts(texts):
        recorder.events.append(f"embed:{len(texts)}")
        if recorder.fail:
            raise EmbeddingsUnavailableError("The embedding service answered 403.")
        return [[float(i), 0.0] for i in range(len(texts))]

    recorder.fail = False
    for module in (ingest, knowledge_bases):
        monkeypatch.setattr(module, "embed_texts", embed_texts)
        monkeypatch.setattr(module, "recreate_collection", recreate_collection)
        monkeypatch.setattr(module, "upsert_chunks", upsert_chunks)
    monkeypatch.setattr(ingest, "get_pool", get_pool)
    monkeypatch.setattr(ingest, "_load_documents", documents)
    monkeypatch.setattr(ingest, "embedding_model_id", lambda: "google:test")
    monkeypatch.setattr(knowledge_bases, "load_documents", lambda folder, root: documents())
    return recorder


@pytest.mark.asyncio
async def test_the_crm_documents_are_embedded_in_one_call_before_the_index_is_replaced(rec):
    summary = await ingest.ingest_documents()
    assert summary.status == "completed" and summary.documents_processed == 2
    first = rec.events.index("embed:2") if "embed:2" in rec.events else rec.events.index("embed:4")
    assert first < rec.events.index("truncate") < rec.events.index("recreate")
    assert (
        sum(e.startswith("embed:") for e in rec.events) == 1
    )  # all chunks of all documents at once


@pytest.mark.asyncio
async def test_a_failed_embedding_leaves_the_crm_index_untouched(rec):
    rec.fail = True
    summary = await ingest.ingest_documents()
    assert summary.status == "failed" and "403" in summary.error
    assert "truncate" not in rec.events and "recreate" not in rec.events
    assert not any(e.startswith("upsert") for e in rec.events)


@pytest.mark.asyncio
async def test_the_vectors_reach_the_right_chunks(rec, monkeypatch):
    stored = []

    async def upsert(points):
        stored.extend(points)

    monkeypatch.setattr(ingest, "upsert_chunks", upsert)
    await ingest.ingest_documents()
    dense = [p.vector[ingest.DENSE] for p in stored]
    assert dense == [[float(i), 0.0] for i in range(len(stored))]  # in order, one vector per chunk
    assert [p.payload["source_path"] for p in stored] == sorted(
        p.payload["source_path"] for p in stored
    )


def test_the_knowledge_base_embeds_before_it_replaces_the_collection(rec, monkeypatch, tmp_path):
    import asyncio

    kb = knowledge_bases.KnowledgeBase(
        id="kb",
        label="KB",
        description="d",
        collection="kb_test",
        built_in=False,
        source_dir=tmp_path,
    )
    assert asyncio.run(knowledge_bases.ingest_knowledge_base(kb)).status == "completed"
    assert (
        rec.events.index("recreate")
        > [i for i, e in enumerate(rec.events) if e.startswith("embed:")][0]
    )
    rec.events.clear()
    rec.fail = True
    summary = asyncio.run(knowledge_bases.ingest_knowledge_base(kb))
    assert summary.status == "failed" and "recreate" not in rec.events
