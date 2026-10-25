"""Stage 3.a: fills a SEPARATE Qdrant collection with fake chunks so the
scale-aware search switch can be seen working. The vectors are random, so
answers from this collection are meaningless; only the search path and its
speed are real. Your real `document_chunks` collection is never touched.

Run from apps/api-py (it needs that folder's qdrant-client environment):
  uv run python ../../scripts/seed_fake_chunks.py --count 20000
  uv run python ../../scripts/seed_fake_chunks.py --clean
Then start the API with QDRANT_COLLECTION=document_chunks_demo and call
GET /api/v1/documents/vector-search-info.
"""

import argparse
import asyncio
import os
import random
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

DIMENSIONS = 768  # same as gemini-embedding-001 in the real collection
DEMO_COLLECTION = "document_chunks_demo"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20000)
    parser.add_argument("--clean", action="store_true", help="delete the demo collection and exit")
    parser.add_argument("--url", default=os.environ.get("QDRANT_URL", "http://localhost:6333"))
    args = parser.parse_args()

    client = AsyncQdrantClient(url=args.url)
    try:
        if await client.collection_exists(DEMO_COLLECTION):
            await client.delete_collection(DEMO_COLLECTION)
        if args.clean:
            print(f"Deleted {DEMO_COLLECTION}")
            return

        await client.create_collection(
            DEMO_COLLECTION,
            vectors_config=VectorParams(size=DIMENSIONS, distance=Distance.COSINE),
        )
        rng = random.Random(42)
        batch = 500
        for start in range(0, args.count, batch):
            points = [
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=[rng.gauss(0, 1) for _ in range(DIMENSIONS)],
                    payload={
                        "document_id": i,
                        "chunk_index": 0,
                        "content": f"Fake chunk {i}",
                        "char_start": 0,
                        "char_end": 12,
                        "document_title": f"Fake document {i}",
                        "source_path": f"fake/{i}.md",
                        "doc_type": "fake",
                        "company_id": i % 5 + 1,
                        "company_name": f"Fake Co {i % 5 + 1}",
                    },
                )
                for i in range(start, min(start + batch, args.count))
            ]
            await client.upsert(DEMO_COLLECTION, points=points)
        print(f"Seeded {args.count} fake chunks into {DEMO_COLLECTION} at {args.url}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
