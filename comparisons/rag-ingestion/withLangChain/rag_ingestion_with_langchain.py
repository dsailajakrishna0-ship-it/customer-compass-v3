"""RAG ingestion with LangChain: Read, Chunk, Embed, Store, each step a LangChain class.

Read: `TextLoader` (langchain-community). Chunk: `RecursiveCharacterTextSplitter` (600 characters,
100 overlap). Embed: `GoogleGenerativeAIEmbeddings` (Gemini). Store: `QdrantVectorStore`
(langchain-qdrant). What we add: the front matter, the order (embed first, then replace the
collection, so a failed run leaves the old data), the dimension check and the request count.
Decisions and measurements: docs/adr/0038.
"""

from __future__ import annotations

import time
from pathlib import Path

import frontmatter
from lab_common.chat import UnavailableError
from lab_common.ingest import IngestResult
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

COLLECTION = "compare_withlangchain"
CHUNK_SIZE = 600
CHUNK_OVERLAP = 100
BATCH_SIZE = 100  # texts per embedding request


def read_documents(folder: Path, limit: int | None) -> list[Document]:
    """The Markdown files of the folder in file name order, the first `limit` of them. The loader
    keeps the front matter in the text, so it is cut off here and becomes title and company."""
    paths = sorted(folder.glob("*.md"))[:limit]
    documents: list[Document] = []
    for path in paths:
        for loaded in TextLoader(str(path), encoding="utf-8").load():
            post = frontmatter.loads(loaded.page_content)
            documents.append(
                Document(
                    page_content=post.content,
                    metadata={
                        "source": path.name,
                        "title": str(post.get("title", path.stem)),
                        "company": str(post.get("company", "")),
                    },
                )
            )
    return documents


class CheckedEmbeddings(Embeddings):
    """Wraps the embedding model: 100 texts per request, every vector must have the agreed length,
    and the requests are counted. A failure is reported by kind, never by the service's own text."""

    def __init__(self, inner: Embeddings, dimensions: int) -> None:
        self._inner = inner
        self._dimensions = dimensions
        self.requests = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            self.requests += 1
            try:
                got = self._inner.embed_documents(batch)
            except Exception as exc:  # noqa: BLE001
                raise UnavailableError(
                    f"The embedding service failed ({type(exc).__name__})."
                ) from exc
            if len(got) != len(batch) or any(len(v) != self._dimensions for v in got):
                raise UnavailableError(
                    f"The embedding service answered vectors of the wrong number or length (expected {self._dimensions})."
                )
            vectors.extend(got)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class PrecomputedEmbeddings(Embeddings):
    """Hands the store vectors that were already computed, so the store does not embed again."""

    def __init__(self, vectors_by_text: dict[str, list[float]]) -> None:
        self._vectors = vectors_by_text

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors[t] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vectors[text]


class LangChainIngest:
    approach = "withLangChain"

    def __init__(
        self,
        source_dir: Path,
        *,
        embeddings: Embeddings | None = None,
        api_key: str = "",
        embedding_model: str = "gemini-embedding-001",
        embedding_base_url: str | None = None,
        dimensions: int = 768,
        qdrant: QdrantClient | None = None,
        qdrant_url: str = "http://localhost:26333",
    ) -> None:
        self._source = source_dir
        self._embeddings = embeddings  # a stand-in in tests; None means Gemini, built per run
        self._api_key = api_key
        self._model = embedding_model
        self._base_url = embedding_base_url
        self._dimensions = dimensions
        self._qdrant = qdrant
        self._qdrant_url = qdrant_url

    def _embedding_model(self) -> Embeddings:
        if self._embeddings is not None:
            return self._embeddings
        if not self._api_key.strip():
            raise UnavailableError("GOOGLE_API_KEY is not set. Put it in the environment.")
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=f"models/{self._model}",
            google_api_key=self._api_key,
            base_url=self._base_url,
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=self._dimensions,
        )

    def run(self, limit: int | None) -> IngestResult:
        started = time.monotonic()
        model = self._embedding_model()
        documents = read_documents(self._source, limit)
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, add_start_index=True
        )
        chunks = splitter.split_documents(documents)

        checked = CheckedEmbeddings(model, self._dimensions)
        vectors = checked.embed_documents([c.page_content for c in chunks]) if chunks else []

        client = self._qdrant or QdrantClient(url=self._qdrant_url, timeout=30)
        try:
            # Replace only now that every vector exists: a failed embedding leaves the old data.
            if client.collection_exists(COLLECTION):
                client.delete_collection(COLLECTION)
            client.create_collection(
                COLLECTION,
                vectors_config=VectorParams(size=self._dimensions, distance=Distance.COSINE),
            )
            if chunks:
                store = QdrantVectorStore(
                    client=client,
                    collection_name=COLLECTION,
                    embedding=PrecomputedEmbeddings(
                        {c.page_content: v for c, v in zip(chunks, vectors, strict=True)}
                    ),
                    # off: each of these makes the store embed a dummy text or read the collection
                    validate_embeddings=False,
                    validate_collection_config=False,
                )
                store.add_documents(chunks)
        except UnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UnavailableError(f"Qdrant failed ({type(exc).__name__}).") from exc
        return IngestResult(
            collection=COLLECTION,
            documents=len(documents),
            chunks=len(chunks),
            embedding_requests=checked.requests,
            embedding_model=self._model,
            dimensions=self._dimensions,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
