"""Ingestion then retrieval against a real Qdrant server (a throw-away container), with a fake
embedding model. Skipped unless QDRANT_URL is set:

    docker run -d --name cc-e5-qdrant -p 26335:6333 qdrant/qdrant:v1.20.0
    QDRANT_URL=http://localhost:26335 just comparisons-test
"""

import os
from pathlib import Path

import pytest
from lab_common.chat import UnavailableError
from qdrant_client import QdrantClient
from rag_ingestion_with_langchain import LangChainIngest
from rag_retrieval_with_langchain import COLLECTION, LangChainRetrieve
from test_ingestion_langchain import FakeEmbeddings

URL = os.environ.get("QDRANT_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set QDRANT_URL to a throw-away Qdrant to run this")
SAMPLE = Path(__file__).resolve().parents[2] / "sample-data" / "documents"


@pytest.fixture
def client():
    qdrant = QdrantClient(url=URL)
    if qdrant.collection_exists(COLLECTION):
        qdrant.delete_collection(COLLECTION)
    return qdrant


def test_a_missing_collection_on_a_real_server_says_to_run_the_ingestion_first(client):
    with pytest.raises(UnavailableError, match="Run the withLangChain ingestion first"):
        LangChainRetrieve(embeddings=FakeEmbeddings(), dimensions=8, qdrant_url=URL).search(
            "q", 3, 0.6
        )


def test_what_was_ingested_is_found_with_its_own_text_as_the_question_and_run_twice_does_not_duplicate(
    client,
):
    model = FakeEmbeddings(dimensions=8)
    ingest = LangChainIngest(SAMPLE, embeddings=model, dimensions=8, qdrant_url=URL)
    first = ingest.run(None)
    ingest.run(None)
    assert client.count(COLLECTION).count == first.chunks == 29
    point = client.scroll(COLLECTION, limit=1, with_payload=True)[0][0]
    text = point.payload["page_content"]
    result = LangChainRetrieve(embeddings=model, dimensions=8, qdrant_url=URL).search(text, 4, 0.6)
    assert result.hits[0].text == text and result.hits[0].score == pytest.approx(1.0, abs=1e-6)
    assert (
        result.considered == 4
        and result.hits[0].chunk_index == point.payload["metadata"]["chunk_index"]
    )
