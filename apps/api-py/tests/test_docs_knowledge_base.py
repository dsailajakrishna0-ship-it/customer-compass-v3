"""Step 4 (ADR 0045): the project's own documentation as a knowledge base. No key, no network, no
containers: a real Qdrant engine in this process and a fake embedding model, as in test_knowledge_bases."""

import math
import re
import zlib
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from app.config import reset_settings
from app.main import app
from app.rag import docs_reader, knowledge_bases, qdrant_store, retrieve
from app.rag.embeddings import EmbeddingsUnavailableError
from app.rag.multi_source import KbChunk
from app.routes.multi_chat import answer_hints

pytestmark = pytest.mark.filterwarnings("ignore:Local mode performs exact")

DIMENSIONS = 64
DOCS = "/api/v1/knowledge-bases/docs"


def fake_vector(text: str) -> list[float]:
    values = [0.0] * DIMENSIONS
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        values[zlib.crc32(word.encode()) % DIMENSIONS] += 1.0
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


@pytest.fixture
def stack(monkeypatch):
    client = AsyncQdrantClient(":memory:")
    state = SimpleNamespace(embedded=[], fail=False)

    async def embed_texts(texts):
        state.embedded.append(len(texts))
        if state.fail:
            raise EmbeddingsUnavailableError("The embedding service answered 403.")
        return [fake_vector(t) for t in texts]

    async def embed_text(text):
        return fake_vector(text)

    monkeypatch.setattr(qdrant_store, "_client", client)
    monkeypatch.setattr(qdrant_store, "embedding_dimensions", lambda: DIMENSIONS)
    monkeypatch.setattr(qdrant_store, "embedding_model_id", lambda: "fake:bag-of-words")
    monkeypatch.setattr(retrieve, "embedding_model_id", lambda: "fake:bag-of-words")
    monkeypatch.setattr(retrieve, "embed_text", embed_text)
    monkeypatch.setattr(knowledge_bases, "embed_texts", embed_texts)
    monkeypatch.setattr(retrieve, "MIN_SIMILARITY", 0.05)
    retrieve.reset_count_cache()
    retrieve.reset_index_model_check()
    yield state
    retrieve.reset_count_cache()
    retrieve.reset_index_model_check()


@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    """A small `docs/` folder: two top-level guides, two stage guides, and an ADR and a V2 page that must be left out."""
    root = tmp_path / "docs"
    (root / "stages").mkdir(parents=True)
    (root / "adr").mkdir()
    (root / "v2-baseline").mkdir()
    (root / "smoke-test.md").write_text(
        "# Smoke test: the quick path\n\nRun just up, then curl localhost:8001/health.\n"
    )
    (root / "troubleshooting.md").write_text(
        "---\nowner: someone\n---\n\n# Troubleshooting\n\nIf the db container is unhealthy, recreate it.\n"
    )
    (root / "no-heading.md").write_text(
        "Just text with no heading at all about embedding quotas.\n"
    )
    (root / "stages" / "04-retrieval-upgrade.md").write_text(
        "# Stage 4: retrieval upgrade\n\nHybrid search merges two rankings.\n"
    )
    (root / "stages" / "05-observability.md").write_text(
        "# Stage 5: observability\n\nTracing sends spans over OTLP.\n"
    )
    (root / "adr" / "0001-decision.md").write_text(
        "# ADR 1\n\nA decision nobody should find in the docs knowledge base.\n"
    )
    (root / "v2-baseline" / "old.md").write_text("# Old V2 page\n\nSuperseded.\n")
    monkeypatch.setenv("DOCS_KNOWLEDGE_BASE", "true")
    monkeypatch.setenv("DOCS_DIR", str(root))
    reset_settings()
    yield root
    reset_settings()


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def rows(client):
    return {row["id"]: row for row in (await client.get("/api/v1/knowledge-bases")).json()}


# ---- the reader


def test_a_page_title_is_its_first_heading_or_else_the_file_name():
    assert docs_reader.page_title("intro\n\n# The Title\n\n## Sub\n", "stem") == "The Title"
    assert docs_reader.page_title("## only a sub heading\n", "stem") == "stem"


def test_the_reader_takes_one_folder_level_at_a_time_and_drops_front_matter(docs_dir):
    top = docs_reader.folder_paths(docs_dir, ".")
    assert [p.name for p in top] == [
        "no-heading.md",
        "smoke-test.md",
        "troubleshooting.md",
    ]  # no subfolders
    page = docs_reader.read_page(docs_dir / "troubleshooting.md", docs_dir.parent)
    assert (page.title, page.doc_type, page.company_name) == ("Troubleshooting", "product", None)
    assert (
        "owner: someone" not in page.segments[0].text
        and page.source_path == "docs/troubleshooting.md"
    )
    assert docs_reader.read_page(docs_dir / "no-heading.md", docs_dir.parent).title == "no-heading"


def test_a_missing_folder_is_an_error_not_an_empty_knowledge_base(tmp_path):
    with pytest.raises(FileNotFoundError):
        docs_reader.folder_paths(tmp_path, "stages")


# ---- the setting


@pytest.mark.asyncio
async def test_the_docs_knowledge_base_is_off_unless_asked_for(stack, client):
    reset_settings()
    assert list(await rows(client)) == ["crm", "agri-supply"]


@pytest.mark.asyncio
async def test_switched_on_it_is_listed_with_its_folders_and_a_description_that_routes_how_to_questions(
    stack, client, docs_dir
):
    row = (await rows(client))["docs"]
    assert (
        row["collection"] == "document_chunks_docs"
        and row["builtIn"] is False
        and row["chunks"] == 0
    )
    assert "run" in row["description"] and "troubleshooting" in row["description"]
    kb = knowledge_bases.find_knowledge_base("docs")
    assert (kb.reader, kb.folders) == ("docs", (".", "stages")) and "exactly" in kb.answer_hint


# ---- ingestion


@pytest.mark.asyncio
async def test_ingesting_reads_the_top_level_and_stages_and_leaves_the_adrs_and_v2_pages_out(
    stack, client, docs_dir
):
    body = (await client.post(f"{DOCS}/ingest")).json()
    assert body["status"] == "completed" and body["documentsProcessed"] == 5
    found = (
        await client.post(f"{DOCS}/search", json={"query": "hybrid search merges rankings"})
    ).json()
    assert found["results"][0]["title"] == "Stage 4: retrieval upgrade"
    nothing = (
        await client.post(f"{DOCS}/search", json={"query": "decision nobody should find"})
    ).json()
    assert all("ADR" not in r["title"] for r in nothing["results"])
    assert all("Old V2" not in r["title"] for r in nothing["results"])
    assert stack.embedded == [5]  # all pages embedded in one call


@pytest.mark.asyncio
async def test_ingesting_twice_never_duplicates(stack, client, docs_dir):
    first = (await client.post(f"{DOCS}/ingest")).json()["chunksCreated"]
    second = (await client.post(f"{DOCS}/ingest")).json()["chunksCreated"]
    assert second == first and (await rows(client))["docs"]["chunks"] == first


@pytest.mark.asyncio
async def test_one_folder_alone_refreshes_its_pages_and_keeps_the_rest(stack, client, docs_dir):
    await client.post(f"{DOCS}/ingest")
    total = (await rows(client))["docs"]["chunks"]
    (docs_dir / "stages" / "05-observability.md").write_text(
        "# Stage 5: observability\n\nTracing now also sends metrics.\n"
    )
    stack.embedded.clear()

    body = (await client.post(f"{DOCS}/ingest", params={"folder": "stages"})).json()

    assert body["status"] == "completed" and body["documentsProcessed"] == 2
    assert stack.embedded == [2]  # only the stage pages were embedded
    assert (await rows(client))["docs"]["chunks"] == total  # nothing duplicated, nothing lost
    found = (await client.post(f"{DOCS}/search", json={"query": "tracing metrics"})).json()[
        "results"
    ]
    assert "metrics" in found[0]["snippet"]
    assert "spans over OTLP" not in " ".join(
        r["snippet"] for r in found
    )  # the old text of the page is gone
    top = (
        await client.post(f"{DOCS}/search", json={"query": "smoke test quick path curl health"})
    ).json()["results"]
    assert top[0]["title"] == "Smoke test: the quick path"  # the top-level pages are still there


@pytest.mark.asyncio
async def test_a_folder_ingested_first_creates_the_collection_and_the_other_can_follow_another_day(
    stack, client, docs_dir
):
    first = (await client.post(f"{DOCS}/ingest", params={"folder": "stages"})).json()
    second = (await client.post(f"{DOCS}/ingest", params={"folder": "."})).json()
    assert (first["documentsProcessed"], second["documentsProcessed"]) == (2, 3)
    assert (await rows(client))["docs"]["chunks"] == first["chunksCreated"] + second[
        "chunksCreated"
    ]


@pytest.mark.asyncio
async def test_document_numbers_do_not_change_when_one_folder_is_ingested_alone(
    stack, client, docs_dir
):
    await client.post(f"{DOCS}/ingest")
    full = (
        await client.post(f"{DOCS}/search", json={"query": "tracing spans otlp", "topK": 1})
    ).json()["results"][0]
    await client.post(f"{DOCS}/ingest", params={"folder": "stages"})
    again = (
        await client.post(f"{DOCS}/search", json={"query": "tracing spans otlp", "topK": 1})
    ).json()["results"][0]
    assert again["documentId"] == full["documentId"]


@pytest.mark.asyncio
async def test_an_unknown_folder_and_a_folder_on_another_knowledge_base_are_422(
    stack, client, docs_dir
):
    unknown = await client.post(f"{DOCS}/ingest", params={"folder": "adr"})
    assert unknown.status_code == 422 and "Choose one of: ., stages" in unknown.json()["detail"]
    other = await client.post("/api/v1/knowledge-bases/agri-supply/ingest", params={"folder": "x"})
    assert other.status_code == 422 and "rebuilt as a whole" in other.json()["detail"]


@pytest.mark.asyncio
async def test_a_failed_embedding_call_leaves_the_knowledge_base_as_it_was(stack, client, docs_dir):
    await client.post(f"{DOCS}/ingest")
    before = (await rows(client))["docs"]["chunks"]
    stack.fail = True
    for params in ({}, {"folder": "stages"}):
        body = (await client.post(f"{DOCS}/ingest", params=params)).json()
        assert body["status"] == "failed" and "403" in body["error"]
    assert (await rows(client))["docs"]["chunks"] == before


@pytest.mark.asyncio
async def test_a_missing_docs_folder_is_reported_in_the_summary(
    stack, client, docs_dir, monkeypatch, tmp_path
):
    monkeypatch.setenv("DOCS_DIR", str(tmp_path / "nowhere"))
    reset_settings()
    body = (await client.post(f"{DOCS}/ingest")).json()
    assert body["status"] == "failed" and "nowhere" in body["error"]


# ---- the answer hint


def chunk(kb):
    return KbChunk(kb, SimpleNamespace())


def test_the_hint_of_a_knowledge_base_reaches_the_answer_only_when_that_knowledge_base_supplied_a_chunk(
    docs_dir,
):
    assert "commands" in answer_hints([chunk("docs")]) and "code block" in answer_hints(
        [chunk("docs")]
    )
    assert answer_hints([chunk("agri-supply"), chunk("crm")]) == ""
