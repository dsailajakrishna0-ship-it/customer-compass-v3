"""RAG retrieval with LangChain: `QdrantVectorStore.similarity_search_with_score` does the embedding
of the question and the nearest-neighbour search in one call, over the collection that the
withLangChain ingestion (E5.2) filled.

What we add: the floor (a cosine of at least 0.60, applied here on the raw score because the
store's relevance-score and retriever helpers rescale the score), `considered` and `kept`, the
query task type, the dimension check, the request count and the safe error messages.
Decisions and measurements: docs/adr/0039.
"""

from __future__ import annotations

import time

from lab_common.chat import UnavailableError
from lab_common.retrieve import Hit, RetrieveResult
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse

COLLECTION = "compare_withlangchain"  # the collection the withLangChain ingestion writes


class CountingQueryEmbeddings(Embeddings):
    """Wraps the embedding model: counts requests, checks the vector length, reports a failure by
    kind and never by the service's own text."""

    def __init__(self, inner: Embeddings, dimensions: int) -> None:
        self._inner = inner
        self._dimensions = dimensions
        self.requests = 0

    def embed_query(self, text: str) -> list[float]:
        self.requests += 1
        try:
            vector = self._inner.embed_query(text)
        except Exception as exc:  # noqa: BLE001
            raise UnavailableError(f"The embedding service failed ({type(exc).__name__}).") from exc
        if len(vector) != self._dimensions:
            raise UnavailableError(
                f"The embedding service answered a vector of the wrong length (expected {self._dimensions})."
            )
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


class LangChainRetrieve:
    approach = "withLangChain"

    def __init__(
        self,
        *,
        embeddings: Embeddings | None = None,
        api_key: str = "",
        embedding_model: str = "gemini-embedding-001",
        embedding_base_url: str | None = None,
        dimensions: int = 768,
        qdrant: QdrantClient | None = None,
        qdrant_url: str = "http://localhost:26333",
    ) -> None:
        self._embeddings = embeddings  # a stand-in in tests; None means Gemini
        self._api_key = api_key
        self._model = embedding_model
        self._base_url = embedding_base_url or None
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
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=self._dimensions,
        )

    def search(self, query: str, top_k: int, min_similarity: float) -> RetrieveResult:
        started = time.monotonic()
        embeddings = CountingQueryEmbeddings(self._embedding_model(), self._dimensions)
        client = self._qdrant or QdrantClient(url=self._qdrant_url, timeout=30)
        try:
            store = QdrantVectorStore(
                client=client,
                collection_name=COLLECTION,
                embedding=embeddings,
                # off: each of these makes the store embed a dummy text or read the collection
                validate_embeddings=False,
                validate_collection_config=False,
            )
            # No score_threshold: it would hide how many chunks the store returned.
            found = store.similarity_search_with_score(query, k=top_k)
        except UnavailableError:
            raise
        except (ValueError, UnexpectedResponse) as exc:
            # the in-memory client raises ValueError("... not found"), a real server a 404 response
            missing = "not found" in str(exc).lower() or getattr(exc, "status_code", None) == 404
            if missing:
                raise UnavailableError(
                    f"The collection {COLLECTION} does not exist. Run the withLangChain ingestion first."
                ) from exc
            raise UnavailableError(f"Qdrant failed ({type(exc).__name__}).") from exc
        except Exception as exc:  # noqa: BLE001
            raise UnavailableError(f"Qdrant failed ({type(exc).__name__}).") from exc
        hits = [
            Hit(
                score=float(score),
                title=doc.metadata.get("title"),
                source=doc.metadata.get("source"),
                company=doc.metadata.get("company"),
                chunk_index=doc.metadata.get("chunk_index"),
                text=doc.page_content,
            )
            for doc, score in found
            if score >= min_similarity
        ]
        return RetrieveResult(
            collection=COLLECTION,
            min_similarity=min_similarity,
            considered=len(found),
            hits=hits,
            embedding_requests=embeddings.requests,
            embedding_model=self._model,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
