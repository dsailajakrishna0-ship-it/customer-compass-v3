"""Teaching demo: vector-index trade-offs in Qdrant, on synthetic data.

Compares exact (flat) search against HNSW at several `hnsw_ef` values
(recall@10 vs latency), then filtered search with and without a payload
index. Needs a real Qdrant server (the in-memory client is brute-force only):

    docker run -d --rm --name qdrant-demo -p 6335:6333 qdrant/qdrant
    cd apps/api-py && uv run python ../../evals/vector_index_demo.py http://localhost:6335

Numbers come from random clustered vectors, not our 16 documents; the
shape of the trade-off is what matters, not the absolute values.
"""

import sys
import time

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    OptimizersConfigDiff,
    PayloadSchemaType,
    PointStruct,
    SearchParams,
    VectorParams,
)

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:6335"
COLLECTION = "index_demo"
N, DIM, CLUSTERS, QUERIES, K = 20_000, 768, 100, 100, 10
COMPANIES = 7  # same order of magnitude as the sample data

rng = np.random.default_rng(42)
centers = rng.normal(size=(CLUSTERS, DIM))


def sample(n: int) -> np.ndarray:
    vectors = centers[rng.integers(0, CLUSTERS, n)] + 0.6 * rng.normal(size=(n, DIM))
    return (vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).astype(np.float32)


def timed_search(client: QdrantClient, queries: np.ndarray, flt: Filter | None, params: SearchParams):
    ids, started = [], time.perf_counter()
    for q in queries:
        hits = client.query_points(COLLECTION, query=q.tolist(), query_filter=flt, limit=K, search_params=params).points
        ids.append({h.id for h in hits})
    return ids, (time.perf_counter() - started) / len(queries) * 1000


def recall(found: list[set[int]], truth: list[set[int]]) -> float:
    return sum(len(f & t) / max(len(t), 1) for f, t in zip(found, truth)) / len(truth)


def main() -> None:
    client = QdrantClient(url=URL, timeout=120)
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        COLLECTION,
        vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
        hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
        optimizers_config=OptimizersConfigDiff(indexing_threshold=1000),
    )
    vectors = sample(N)
    for start in range(0, N, 1000):
        client.upsert(
            COLLECTION,
            [
                PointStruct(id=i, vector=vectors[i].tolist(), payload={"company_id": int(i % COMPANIES)})
                for i in range(start, start + 1000)
            ],
        )
    while client.get_collection(COLLECTION).status.value != "green":
        time.sleep(1)
    info = client.get_collection(COLLECTION)
    print(f"{N} vectors, {DIM} dims, cosine; indexed_vectors_count={info.indexed_vectors_count}\n")

    queries = sample(QUERIES)
    exact_ids, exact_ms = timed_search(client, queries, None, SearchParams(exact=True))
    print("Unfiltered search (recall@10 against exact search)")
    print(f"  exact (flat)   recall 1.00  {exact_ms:7.2f} ms/query")
    for ef in (8, 32, 128):
        ids, ms = timed_search(client, queries, None, SearchParams(hnsw_ef=ef))
        print(f"  HNSW ef={ef:<4}  recall {recall(ids, exact_ids):.2f}  {ms:7.2f} ms/query")

    flt = Filter(must=[FieldCondition(key="company_id", match=MatchValue(value=3))])
    truth, _ = timed_search(client, queries, flt, SearchParams(exact=True))
    ids, ms = timed_search(client, queries, flt, SearchParams(hnsw_ef=32))
    print("\nFiltered search, company_id = 3 (ef=32)")
    print(f"  no payload index   recall {recall(ids, truth):.2f}  {ms:7.2f} ms/query")
    client.create_payload_index(COLLECTION, "company_id", PayloadSchemaType.INTEGER)
    time.sleep(2)
    ids, ms = timed_search(client, queries, flt, SearchParams(hnsw_ef=32))
    print(f"  with payload index recall {recall(ids, truth):.2f}  {ms:7.2f} ms/query")

    client.delete_collection(COLLECTION)


main()
