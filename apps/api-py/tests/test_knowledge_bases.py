"""Knowledge bases (ADR 0029): a second corpus in its own collection, found only through its own
search, never disturbed by (or disturbing) the CRM documents. No key, no network, no containers: a real
Qdrant engine running in this process (`:memory:`) and a fake embedding model, so what is checked is the
flow and the isolation, not the quality of the ranking."""

import asyncio
import json
import math
import re
import zlib
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

from app.config import get_settings, reset_settings
from app.main import app
from app.rag import knowledge_bases, qdrant_store, retrieve
from app.rag.sparse import document_vector

pytestmark = pytest.mark.filterwarnings("ignore:Local mode performs exact")

DIMENSIONS = 64
MODEL = "fake:bag-of-words"


def fake_vector(text: str) -> list[float]:
    """A bag of hashed words, normalised: texts that share words are close, the same text is identical."""
    values = [0.0] * DIMENSIONS
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        values[zlib.crc32(word.encode()) % DIMENSIONS] += 1.0
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


@pytest.fixture
def stack(monkeypatch):
    """An in-process Qdrant and fake embeddings wired into the code under test."""
    client = AsyncQdrantClient(":memory:")
    model = SimpleNamespace(id=MODEL)

    async def embed_texts(texts):
        return [fake_vector(t) for t in texts]

    async def embed_text(text):
        return fake_vector(text)

    monkeypatch.setattr(qdrant_store, "_client", client)
    monkeypatch.setattr(qdrant_store, "embedding_dimensions", lambda: DIMENSIONS)
    monkeypatch.setattr(qdrant_store, "embedding_model_id", lambda: model.id)
    monkeypatch.setattr(retrieve, "embedding_model_id", lambda: model.id)
    monkeypatch.setattr(retrieve, "embed_text", embed_text)
    monkeypatch.setattr(knowledge_bases, "embed_texts", embed_texts)
    # a bag of words scores a short question low against a whole chunk; the floor is not under test here
    monkeypatch.setattr(retrieve, "MIN_SIMILARITY", 0.05)
    retrieve.reset_count_cache()
    retrieve.reset_index_model_check()
    yield model
    retrieve.reset_count_cache()
    retrieve.reset_index_model_check()


CRM_CHUNKS = [
    ("Renewal planning call", "acme-call-renewal.md", "Maya asked about the renewal of the premium plan and the discount"),
    ("Pricing email", "acme-email-discount.md", "Ravi asked for the pricing breakdown and a multi site discount"),
    ("Support ticket", "acme-support-export-timeout.md", "The export history button times out after ninety days of data"),
]  # fmt: skip


async def seed_crm() -> None:
    """The CRM documents' collection, filled the way the CRM ingestion fills it (the configured collection)."""
    await qdrant_store.recreate_collection()
    await qdrant_store.upsert_chunks(
        [
            PointStruct(
                id=f"00000000-0000-0000-0000-00000000000{i}",
                vector={qdrant_store.DENSE: fake_vector(text), qdrant_store.SPARSE: document_vector(text)},
                payload={
                    "document_id": i, "chunk_index": 0, "content": text, "document_title": title,
                    "source_path": f"sample-data/documents/{path}", "doc_type": "note",
                    "company_id": None, "company_name": None,
                },
            )
            for i, (title, path, text) in enumerate(CRM_CHUNKS, start=1)
        ]
    )  # fmt: skip


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


AGRI = "/api/v1/knowledge-bases/agri-supply"
SPRAY = "How long must workers stay out of a block after spraying? re-entry interval"


async def list_rows(client):
    return {row["id"]: row for row in (await client.get("/api/v1/knowledge-bases")).json()}


@pytest.mark.asyncio
async def test_the_list_shows_the_built_in_and_the_extra_knowledge_base(stack, client):
    rows = await list_rows(client)

    assert list(rows) == ["crm", "agri-supply"]
    assert rows["crm"]["builtIn"] is True and rows["crm"]["collection"] == "document_chunks"
    assert rows["agri-supply"]["builtIn"] is False
    assert rows["agri-supply"]["collection"] == "document_chunks_agri_supply"
    assert rows["agri-supply"]["chunks"] == 0
    assert "re-entry" in rows["agri-supply"]["description"]
    assert "cold chain" in rows["agri-supply"]["description"]


@pytest.mark.asyncio
async def test_ingesting_reads_the_eight_documents_into_the_extra_collection_only(stack, client):
    await seed_crm()

    reply = await client.post(f"{AGRI}/ingest")

    body = reply.json()
    assert reply.status_code == 200
    assert body["status"] == "completed" and body["documentsProcessed"] == 8
    assert body["chunksCreated"] >= 8 and body["error"] is None
    rows = await list_rows(client)
    assert rows["agri-supply"]["chunks"] == body["chunksCreated"]
    assert rows["crm"]["chunks"] == len(CRM_CHUNKS)  # the CRM collection is untouched


@pytest.mark.asyncio
async def test_ingesting_twice_never_duplicates(stack, client):
    first = (await client.post(f"{AGRI}/ingest")).json()["chunksCreated"]
    second = (await client.post(f"{AGRI}/ingest")).json()["chunksCreated"]

    assert second == first
    assert (await list_rows(client))["agri-supply"]["chunks"] == first


@pytest.mark.asyncio
async def test_a_search_of_the_extra_knowledge_base_returns_only_its_own_documents(stack, client):
    await seed_crm()
    await client.post(f"{AGRI}/ingest")

    reply = await client.post(f"{AGRI}/search", json={"query": SPRAY})

    body = reply.json()
    assert reply.status_code == 200 and body["knowledgeBase"] == "agri-supply"
    assert body["results"], "the search found nothing"
    assert all("knowledge-bases/agri-supply/" in r["sourcePath"] for r in body["results"])
    # a fake embedding cannot promise the best match first, only that the right document is found
    assert any(r["title"].startswith("Crop protection product handbook") for r in body["results"])
    assert set(body["results"][0]) >= {
        "number",
        "documentId",
        "title",
        "sourcePath",
        "docType",
        "similarity",
        "snippet",
    }


@pytest.mark.asyncio
async def test_the_two_corpora_never_appear_in_each_others_search(stack, client):
    await seed_crm()
    await client.post(f"{AGRI}/ingest")

    crm = (await client.post("/api/v1/knowledge-bases/crm/search", json={"query": SPRAY})).json()
    agri = (
        await client.post(
            f"{AGRI}/search", json={"query": "Maya renewal premium plan discount pricing"}
        )
    ).json()

    assert all("knowledge-bases" not in r["sourcePath"] for r in crm["results"])
    assert all(r["sourcePath"].startswith("sample-data/documents/") for r in crm["results"])
    assert all("sample-data/documents/" not in r["sourcePath"] for r in agri["results"])


@pytest.mark.asyncio
async def test_rebuilding_the_crm_collection_does_not_wipe_the_extra_one(stack, client):
    await seed_crm()
    chunks = (await client.post(f"{AGRI}/ingest")).json()["chunksCreated"]

    await seed_crm()  # what the CRM ingestion does: drop and recreate its own collection
    await seed_crm()

    rows = await list_rows(client)
    assert rows["agri-supply"]["chunks"] == chunks and rows["crm"]["chunks"] == len(CRM_CHUNKS)
    assert (await client.post(f"{AGRI}/search", json={"query": "cold chain seedlings"})).json()[
        "results"
    ]


@pytest.mark.asyncio
async def test_searching_before_the_first_ingestion_finds_nothing_instead_of_failing(stack, client):
    reply = await client.post(f"{AGRI}/search", json={"query": "cold chain"})

    assert reply.status_code == 200 and reply.json()["results"] == []


@pytest.mark.asyncio
async def test_the_crm_knowledge_base_keeps_its_own_ingest_route(stack, client):
    reply = await client.post("/api/v1/knowledge-bases/crm/ingest")

    assert reply.status_code == 400
    assert "POST /api/v1/documents/ingest" in reply.json()["detail"]


@pytest.mark.asyncio
async def test_an_unknown_knowledge_base_is_a_404(stack, client):
    assert (await client.post("/api/v1/knowledge-bases/nope/ingest")).status_code == 404
    reply = await client.post("/api/v1/knowledge-bases/nope/search", json={"query": "x"})
    assert reply.status_code == 404 and "nope" in reply.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body, kind",
    [({}, "missing"), ({"query": ""}, "string_too_short"), ({"query": "   "}, "string_too_short"),
     ({"query": "x", "topK": 0}, "greater_than_equal"), ({"query": "x", "topK": 21}, "less_than_equal")],
)  # fmt: skip
async def test_a_bad_search_is_a_422_with_fastapis_problems(stack, client, body, kind):
    reply = await client.post(f"{AGRI}/search", json=body)

    assert reply.status_code == 422
    assert reply.json()["detail"][0]["type"] == kind


@pytest.mark.asyncio
async def test_each_collection_remembers_its_own_embedding_model(stack, client):
    await seed_crm()
    await client.post(f"{AGRI}/ingest")
    assert (await client.post(f"{AGRI}/search", json={"query": "cold chain"})).status_code == 200

    stack.id = "fake:another-model"  # the configured model changes after both were built
    knowledge_bases_reply = await client.post(f"{AGRI}/search", json={"query": "cold chain"})
    crm_reply = await client.post("/api/v1/knowledge-bases/crm/search", json={"query": "renewal"})

    assert knowledge_bases_reply.status_code == 503
    assert (
        "POST /api/v1/knowledge-bases/agri-supply/ingest" in knowledge_bases_reply.json()["detail"]
    )
    assert crm_reply.status_code == 503
    assert "POST /api/v1/documents/ingest" in crm_reply.json()["detail"]


@pytest.mark.asyncio
async def test_a_passed_check_for_one_collection_does_not_excuse_another(stack, client):
    """The model check is cached; the cache is per collection, so the first collection's pass must not
    let a mismatched second collection through."""
    await seed_crm()
    await client.post(f"{AGRI}/ingest")
    assert (
        await client.post("/api/v1/knowledge-bases/crm/search", json={"query": "renewal"})
    ).status_code == 200
    await qdrant_store.get_client().delete_collection("document_chunks_agri_supply")
    stack.id = "fake:old"
    await client.post(f"{AGRI}/ingest")  # rebuilt under the "old" model
    stack.id = MODEL  # configured model is back to what the CRM collection has

    assert (
        await client.post("/api/v1/knowledge-bases/crm/search", json={"query": "renewal"})
    ).status_code == 200
    reply = await client.post(f"{AGRI}/search", json={"query": "cold chain"})
    assert reply.status_code == 503


@pytest.mark.asyncio
async def test_hybrid_search_and_its_exact_words_work_in_a_knowledge_base(
    stack, client, monkeypatch
):
    await client.post(f"{AGRI}/ingest")
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    reset_settings()

    reply = await client.post(f"{AGRI}/search", json={"query": "OV-Insect-40"})

    paths = [r["sourcePath"] for r in reply.json()["results"]]
    # two documents contain the exact term OV-Insect-40; the keyword half of the search finds both
    assert any(p.endswith("pesticide-reentry-intervals.md") for p in paths)


@pytest.mark.asyncio
async def test_two_concurrent_searches_for_two_knowledge_bases_do_not_see_each_other(stack, client):
    await seed_crm()
    await client.post(f"{AGRI}/ingest")

    crm, agri = await asyncio.gather(
        client.post(
            "/api/v1/knowledge-bases/crm/search", json={"query": "renewal discount pricing"}
        ),
        client.post(f"{AGRI}/search", json={"query": "cold chain seedlings temperature"}),
    )

    assert all("knowledge-bases" not in r["sourcePath"] for r in crm.json()["results"])
    assert all("knowledge-bases/agri-supply" in r["sourcePath"] for r in agri.json()["results"])
    assert agri.json()["results"]


@pytest.mark.asyncio
async def test_the_collection_override_is_scoped_to_the_block(stack):
    default = qdrant_store.collection_name()
    with qdrant_store.using_collection("other"):
        assert qdrant_store.collection_name() == "other"
    assert qdrant_store.collection_name() == default


@pytest.mark.asyncio
async def test_an_extra_knowledge_base_can_come_from_the_settings_and_its_own_folder(
    stack, client, monkeypatch, tmp_path
):
    (tmp_path / "welcome.md").write_text(
        "---\ntitle: Dock safety\ntype: note\ndate: 2026-01-01\n---\n\nForklifts yield to pedestrians at every dock door.\n"
    )
    monkeypatch.setenv(
        "KNOWLEDGE_BASES",
        json.dumps(
            [
                {
                    "id": "docks",
                    "label": "Dock rules",
                    "description": "Warehouse dock safety.",
                    "source_dir": str(tmp_path),
                }
            ]
        ),
    )
    reset_settings()

    rows = await list_rows(client)
    ingest = (await client.post("/api/v1/knowledge-bases/docks/ingest")).json()
    found = (
        await client.post(
            "/api/v1/knowledge-bases/docks/search", json={"query": "forklifts pedestrians dock"}
        )
    ).json()

    assert list(rows) == ["crm", "docks"] and rows["docks"]["collection"] == "document_chunks_docks"
    assert ingest["status"] == "completed" and ingest["documentsProcessed"] == 1
    assert found["results"][0]["title"] == "Dock safety"


@pytest.mark.asyncio
async def test_a_missing_folder_is_reported_in_the_summary(stack, client, monkeypatch, tmp_path):
    monkeypatch.setenv(
        "KNOWLEDGE_BASES",
        json.dumps(
            [
                {
                    "id": "ghost",
                    "label": "G",
                    "description": "d",
                    "source_dir": str(tmp_path / "nothing"),
                }
            ]
        ),
    )
    reset_settings()

    reply = await client.post("/api/v1/knowledge-bases/ghost/ingest")

    assert reply.status_code == 502
    assert (
        reply.json()["status"] == "failed" and "Could not find the folder" in reply.json()["error"]
    )


def test_the_settings_refuse_the_built_in_id_and_duplicates(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_BASES", '[{"id": "crm", "label": "x", "description": "d"}]')
    reset_settings()
    with pytest.raises(ValueError, match="crm"):
        get_settings()
    monkeypatch.setenv(
        "KNOWLEDGE_BASES",
        '[{"id": "a", "label": "x", "description": "d"}, {"id": "a", "label": "y", "description": "e"}]',
    )
    reset_settings()
    with pytest.raises(ValueError, match="own id"):
        get_settings()
    monkeypatch.setenv("KNOWLEDGE_BASES", '[{"id": "Bad Id", "label": "x", "description": "d"}]')
    reset_settings()
    with pytest.raises(ValueError):
        get_settings()


def test_the_default_extra_knowledge_base_is_the_farm_supply_handbook():
    [kb] = get_settings().knowledge_bases
    assert kb.id == "agri-supply" and kb.label == "Orchard Valley Agri-Supply handbook"
    assert kb.description.startswith("Handbook of a farm-supply business: crop protection products")
    assert kb.description.endswith("supply agreement renewals and the recall procedure.")
