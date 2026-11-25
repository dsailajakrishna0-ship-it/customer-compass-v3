"""The withLangChain ingestion approach against a fake embedding model and an in-memory Qdrant:
no key, no Docker, no network. The second half measures what the LangChain classes do by
themselves, which is what the comparison is about (see docs/adr/0038)."""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from lab_common.chat import UnavailableError
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from rag_ingestion_with_langchain import (
    BATCH_SIZE,
    COLLECTION,
    CheckedEmbeddings,
    LangChainIngest,
    read_documents,
)

DIMENSIONS = 8
EXPECTED_DOCUMENTS = 16  # the Markdown files of sample-data/documents (measured)
EXPECTED_CHUNKS = 29  # at 600 characters with 100 overlap (measured)
SAMPLE = Path(__file__).resolve().parents[2] / "sample-data" / "documents"


class FakeEmbeddings(Embeddings):
    def __init__(self, dimensions=DIMENSIONS, fail=False):
        self.calls: list[int] = []
        self.dimensions = dimensions
        self.fail = fail

    def embed_documents(self, texts):
        self.calls.append(len(texts))
        if self.fail:
            raise RuntimeError("secret library text http://example.test/key=abc")
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)

    def _vector(self, text):
        digest = hashlib.sha256(text.encode()).digest()
        return [b / 255 for b in digest[: self.dimensions]]


def write(folder: Path, name: str, title: str, company: str, body: str) -> None:
    (folder / name).write_text(
        f"---\ntitle: {title}\ncompany: {company}\n---\n\n{body}\n", encoding="utf-8"
    )


@pytest.fixture
def folder(tmp_path):
    write(tmp_path, "a-first.md", "First note", "Acme", "Acme asked about pricing. " * 5)
    write(tmp_path, "b-second.md", "Second note", "Bo Inc", "Bo wants a demo. " * 5)
    write(tmp_path, "c-third.md", "Third note", "Cy", "Cy renewed. " * 5)
    (tmp_path / "ignored.txt").write_text("not markdown")
    return tmp_path


def ingest(folder, qdrant=None, embeddings=None, **kwargs):
    return LangChainIngest(
        folder,
        embeddings=embeddings or FakeEmbeddings(),
        dimensions=DIMENSIONS,
        qdrant=qdrant or QdrantClient(":memory:"),
        **kwargs,
    )


def test_the_pipeline_reads_cuts_embeds_and_stores(folder):
    client = QdrantClient(":memory:")
    result = ingest(folder, client).run(None)
    assert (result.collection, result.documents, result.dimensions) == (COLLECTION, 3, DIMENSIONS)
    assert result.chunks == 3  # each note is shorter than 600 characters
    assert result.embedding_requests == 1
    assert client.count(COLLECTION).count == 3
    points, _ = client.scroll(COLLECTION, limit=10, with_payload=True)
    first = min(points, key=lambda p: p.payload["metadata"]["source"])
    assert first.payload["metadata"]["title"] == "First note"
    assert first.payload["metadata"]["company"] == "Acme"
    assert first.payload["metadata"]["start_index"] == 0
    assert (
        "---" not in first.payload["page_content"] and "title:" not in first.payload["page_content"]
    )


def test_only_markdown_files_are_read_in_file_name_order_and_limit_keeps_the_first(folder):
    assert [d.metadata["source"] for d in read_documents(folder, None)] == [
        "a-first.md",
        "b-second.md",
        "c-third.md",
    ]
    assert [d.metadata["source"] for d in read_documents(folder, 2)] == [
        "a-first.md",
        "b-second.md",
    ]


def test_running_twice_never_duplicates(folder):
    client = QdrantClient(":memory:")
    ingest(folder, client).run(None)
    ingest(folder, client).run(None)
    assert client.count(COLLECTION).count == 3


def test_a_failed_embedding_leaves_the_old_data_in_place(folder):
    client = QdrantClient(":memory:")
    ingest(folder, client).run(None)
    with pytest.raises(UnavailableError) as info:
        ingest(folder, client, embeddings=FakeEmbeddings(fail=True)).run(None)
    assert "secret" not in str(info.value) and "example.test" not in str(info.value)
    assert "RuntimeError" in str(info.value)
    assert client.count(COLLECTION).count == 3  # the replace happens only after every vector exists


def test_vectors_of_the_wrong_length_are_refused(folder):
    with pytest.raises(UnavailableError, match="wrong number or length"):
        ingest(folder, embeddings=FakeEmbeddings(dimensions=3)).run(None)


def test_texts_go_to_the_embedding_model_100_at_a_time():
    inner = FakeEmbeddings()
    checked = CheckedEmbeddings(inner, DIMENSIONS)
    checked.embed_documents([f"text {i}" for i in range(250)])
    assert inner.calls == [100, 100, 50] and checked.requests == 3 and BATCH_SIZE == 100


def test_no_key_means_no_call(folder):
    with pytest.raises(UnavailableError, match="GOOGLE_API_KEY"):
        LangChainIngest(folder, qdrant=QdrantClient(":memory:")).run(None)


def test_an_unreachable_qdrant_is_reported_by_kind_not_by_address(folder):
    with pytest.raises(UnavailableError) as info:
        LangChainIngest(
            folder,
            embeddings=FakeEmbeddings(),
            dimensions=DIMENSIONS,
            qdrant_url="http://127.0.0.1:9",
        ).run(None)
    assert "127.0.0.1" not in str(info.value) and str(info.value).startswith("Qdrant failed (")


def test_an_empty_folder_replaces_the_collection_with_an_empty_one(tmp_path):
    client = QdrantClient(":memory:")
    result = ingest(tmp_path, client).run(None)
    assert (result.documents, result.chunks, result.embedding_requests) == (0, 0, 0)
    assert client.count(COLLECTION).count == 0


def test_the_sample_documents_give_a_stable_count():
    result = ingest(SAMPLE).run(None)
    assert (result.documents, result.chunks) == (EXPECTED_DOCUMENTS, EXPECTED_CHUNKS)


# What the LangChain classes do on their own (measured, and kept so a library update that changes
# it shows up here).


def test_measured_the_loader_keeps_the_front_matter_in_the_text(folder):
    loaded = TextLoader(str(folder / "a-first.md"), encoding="utf-8").load()
    assert len(loaded) == 1 and loaded[0].page_content.startswith("---\ntitle: First note")
    assert set(loaded[0].metadata) == {"source"}


def test_measured_from_documents_embeds_the_first_text_twice():
    docs = [Document(page_content=f"chunk {i}") for i in range(5)]
    model = FakeEmbeddings()
    QdrantVectorStore.from_documents(
        docs, model, collection_name="x", location=":memory:", force_recreate=True
    )
    assert model.calls == [1, 5]  # one dummy-sized call to learn the dimension, then everything


def test_measured_the_store_embeds_a_dummy_text_when_it_is_built_unless_switched_off():
    from qdrant_client.models import Distance, VectorParams

    client = QdrantClient(":memory:")
    client.create_collection(
        "y", vectors_config=VectorParams(size=DIMENSIONS, distance=Distance.COSINE)
    )
    default = FakeEmbeddings()
    QdrantVectorStore(client=client, collection_name="y", embedding=default)
    off = FakeEmbeddings()
    QdrantVectorStore(
        client=client,
        collection_name="y",
        embedding=off,
        validate_embeddings=False,
        validate_collection_config=False,
    )
    assert default.calls == [1] and off.calls == []


class FakeGemini(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeGemini.seen.append((self.path, dict(self.headers), body))
        data = json.dumps(
            {"embeddings": [{"values": [0.1, 0.2, 0.3]} for _ in body["requests"]]}
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_measured_the_gemini_class_batches_100_per_request_and_sends_the_key_in_a_header():
    FakeGemini.seen = []
    server = HTTPServer(("127.0.0.1", 0), FakeGemini)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        model = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key="KEY-123",
            base_url=f"http://127.0.0.1:{server.server_port}",
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=3,
        )
        vectors = model.embed_documents([f"t{i}" for i in range(250)])
    finally:
        server.shutdown()
    assert len(vectors) == 250
    assert [len(body["requests"]) for _, _, body in FakeGemini.seen] == [100, 100, 50]
    path, headers, body = FakeGemini.seen[0]
    assert path == "/v1beta/models/gemini-embedding-001:batchEmbedContents"
    assert headers["x-goog-api-key"] == "KEY-123" and "KEY-123" not in path
    assert body["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert body["requests"][0]["outputDimensionality"] == 3
