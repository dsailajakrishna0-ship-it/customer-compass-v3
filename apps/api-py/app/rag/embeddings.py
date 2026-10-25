"""Thin client around Google's Generative Language embedding API.

Replaces Ollama's mxbai-embed-large (used by the Express API) with Google's
cloud embedding model for the v2 stack migration (see docs/ for the locked-in
stack decision). Kept separate from ingest/retrieve so both ingestion-time
(document chunks) and query-time (the user's question) embedding calls share
one code path.

Note: Google deprecated "text-embedding-004" (the model originally planned
for this migration) in favor of "gemini-embedding-001", which is used here
instead. It supports Matryoshka representation learning, so we can request a
smaller output dimensionality (768) via `outputDimensionality` while keeping
good embedding quality, instead of the model's full 3072-dim output.
"""

import os

import httpx

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
# Embedding model (Google gemini-embedding-001): turns text into 768-number vectors for similarity search
EMBEDDING_MODEL = os.environ.get("GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIMENSIONS = 768

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embeds a batch of texts, one request per text (this API has no native
    batch-embed endpoint for embedContent), preserving input order."""
    if len(texts) == 0:
        return []
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set. Add it to apps/api-py/.env to use embeddings.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        embeddings: list[list[float]] = []
        for text in texts:
            response = await client.post(
                f"{_API_BASE}/models/{EMBEDDING_MODEL}:embedContent",
                params={"key": GOOGLE_API_KEY},
                json={
                    "model": f"models/{EMBEDDING_MODEL}",
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": EMBEDDING_DIMENSIONS,
                },
            )
            if response.status_code != 200:
                raise RuntimeError(f"Google embeddings request failed: {response.status_code} {response.text}")
            payload = response.json()
            values = payload.get("embedding", {}).get("values")
            if not isinstance(values, list):
                raise RuntimeError("Google did not return an embedding vector for one of the inputs.")
            embeddings.append(values)
    return embeddings


async def embed_text(text: str) -> list[float]:
    [embedding] = await embed_texts([text])
    return embedding
