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

import asyncio
import functools

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


async def _embed_google(texts: list[str]) -> list[list[float]]:
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


# ---------------------------------------------------------------- the open-source option (4.3)


@functools.cache
def _fastembed_model(name: str):
    """Loads the local model once (the first use downloads it, about 70 MB for the default)."""
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise EmbeddingsUnavailableError(
            "EMBEDDING_PROVIDER=fastembed needs the optional package. Install it with "
            "`uv sync --extra local-embeddings` (apps/api-py) and restart the API."
        ) from exc
    return TextEmbedding(model_name=name)


def _fastembed_dimensions(name: str) -> int:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise EmbeddingsUnavailableError(
            "EMBEDDING_PROVIDER=fastembed needs the optional package. Install it with "
            "`uv sync --extra local-embeddings` (apps/api-py) and restart the API."
        ) from exc
    for model in TextEmbedding.list_supported_models():
        if model["model"] == name:
            return int(model["dim"])
    raise EmbeddingsUnavailableError(f"FastEmbed does not list a model named {name!r}.")


async def _embed_fastembed(texts: list[str], *, query: bool) -> list[list[float]]:
    """Runs the local model off the event loop. Models such as bge expect a short instruction in
    front of a *question* (`query_embed`) and none in front of a *document* (`embed`)."""
    model = _fastembed_model(get_settings().fastembed_model)

    def run() -> list[list[float]]:
        vectors = model.query_embed(texts) if query else model.embed(texts)
        return [vector.tolist() for vector in vectors]

    return await asyncio.to_thread(run)


# ---------------------------------------------------------------- the one interface the app uses


def embedding_model_id(provider: str | None = None) -> str:
    """Names the model that made a set of vectors, e.g. `google:gemini-embedding-001`. It is stored
    with the index, so a changed model is noticed and the documents are re-embedded."""
    settings = get_settings()
    provider = provider or settings.embedding_provider
    if provider == "fastembed":
        return f"fastembed:{settings.fastembed_model}"
    return f"google:{settings.google_embedding_model}"


def embedding_dimensions(provider: str | None = None) -> int:
    """How long the vectors are. The collection is created with this size."""
    settings = get_settings()
    provider = provider or settings.embedding_provider
    if provider == "fastembed":
        return _fastembed_dimensions(settings.fastembed_model)
    return EMBEDDING_DIMENSIONS


async def embed_documents(texts: list[str], provider: str | None = None) -> list[list[float]]:
    """Embeds chunks of documents."""
    if not texts:
        return []
    provider = provider or get_settings().embedding_provider
    if provider == "fastembed":
        return await _embed_fastembed(texts, query=False)
    return await _embed_google(texts)


async def embed_query(text: str, provider: str | None = None) -> list[float]:
    """Embeds a question."""
    provider = provider or get_settings().embedding_provider
    if provider == "fastembed":
        [vector] = await _embed_fastembed([text], query=True)
        return vector
    [vector] = await _embed_google([text])
    return vector


async def embed_texts(texts: list[str]) -> list[list[float]]:
    return await embed_documents(texts)


async def embed_text(text: str) -> list[float]:
    return await embed_query(text)
