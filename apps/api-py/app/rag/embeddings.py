"""Thin client around Google's Generative Language embedding API.

Replaces the local embedding model the Express API used with Google's
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

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)

# The embedding model (default Google gemini-embedding-001, see Settings) turns text into
# 768-number vectors for similarity search
EMBEDDING_DIMENSIONS = 768

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class EmbeddingsUnavailableError(RuntimeError):
    """The embedding service cannot be used (no key, Google refused, or an unusable reply). The message
    is safe to show to an API caller: it never contains the key or Google's reply body."""


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embeds a batch of texts, one request per text (this API has no native
    batch-embed endpoint for embedContent), preserving input order."""
    if len(texts) == 0:
        return []
    settings = get_settings()
    api_key = settings.google_api_key.get_secret_value()
    model = settings.google_embedding_model
    if not api_key:
        raise EmbeddingsUnavailableError(
            "GOOGLE_API_KEY is not set. Put it in the .env file in the project root (apps/api-py/.env "
            "if you run the API outside Docker), without a leading #, then restart the API."
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        embeddings: list[list[float]] = []
        for text in texts:
            response = await client.post(
                f"{_API_BASE}/models/{model}:embedContent",
                params={"key": api_key},
                json={
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": EMBEDDING_DIMENSIONS,
                },
            )
            if response.status_code != 200:
                log.warning(
                    "embedding_request_failed",
                    status=response.status_code,
                    body=response.text[:200],
                )
                raise EmbeddingsUnavailableError(
                    f"Google's embedding service answered {response.status_code}: "
                    "check GOOGLE_API_KEY and try again (details are in the API log)."
                )
            payload = response.json()
            values = payload.get("embedding", {}).get("values")
            if not isinstance(values, list):
                raise EmbeddingsUnavailableError(
                    "Google did not return an embedding vector for one of the inputs."
                )
            embeddings.append(values)
    return embeddings


async def embed_text(text: str) -> list[float]:
    [embedding] = await embed_texts([text])
    return embedding
