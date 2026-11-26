"""How the Google embedding call is made (no key, no network): the key travels in a header and never
in the URL, texts go in batches of 100 in input order, and every refusal is a plain message."""

import json

import httpx
import pytest

from app.config import reset_settings
from app.rag import embeddings
from app.rag.embeddings import EmbeddingsUnavailableError

KEY = "test-key-not-real-1234"


class FakeGoogle:
    """A stand-in for Google's batchEmbedContents: the vector of a text is [its length, 0.5]."""

    def __init__(self, status=200, drop_one=False, bad_item=False):
        self.requests: list[httpx.Request] = []
        self.status = status
        self.drop_one = drop_one
        self.bad_item = bad_item

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, text="the service said something with a key in it")
        body = json.loads(request.content)
        items = [
            {"values": [float(len(r["content"]["parts"][0]["text"])), 0.5]}
            for r in body["requests"]
        ]
        if self.drop_one:
            items = items[:-1]
        if self.bad_item:
            items[0] = {"oops": []}
        return httpx.Response(200, json={"embeddings": items})


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", KEY)
    reset_settings()
    fake = FakeGoogle()
    real = httpx.AsyncClient
    monkeypatch.setattr(
        embeddings.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(lambda r: fake(r)), **kwargs),
    )
    yield fake
    reset_settings()


@pytest.mark.asyncio
async def test_the_key_is_in_a_header_and_never_in_the_url(google):
    await embeddings._embed_google(["a chunk"])
    (request,) = google.requests
    assert request.headers["x-goog-api-key"] == KEY
    assert KEY not in str(request.url) and request.url.query == b""


@pytest.mark.asyncio
async def test_texts_go_in_batches_of_100_and_come_back_in_input_order(google):
    texts = [f"{'x' * (i % 7 + 1)}-{i}" for i in range(250)]
    vectors = await embeddings._embed_google(texts)
    assert [len(json.loads(r.content)["requests"]) for r in google.requests] == [100, 100, 50]
    assert [v[0] for v in vectors] == [float(len(t)) for t in texts]


@pytest.mark.asyncio
async def test_each_text_is_sent_as_the_single_text_endpoint_took_it(google):
    await embeddings._embed_google(["hello"])
    (request,) = google.requests
    assert request.url.path.endswith("/models/gemini-embedding-001:batchEmbedContents")
    assert json.loads(request.content) == {
        "requests": [
            {
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": "hello"}]},
                "outputDimensionality": 768,
            }
        ]
    }


@pytest.mark.asyncio
async def test_no_texts_means_no_request(google):
    assert await embeddings._embed_google([]) == []
    assert google.requests == []


@pytest.mark.asyncio
async def test_a_refusal_is_a_plain_message_without_the_key_or_google_reply(google):
    google.status = 403
    with pytest.raises(EmbeddingsUnavailableError) as info:
        await embeddings._embed_google(["x"])
    assert (
        "403" in str(info.value)
        and KEY not in str(info.value)
        and "something with a key" not in str(info.value)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["drop_one", "bad_item"])
async def test_a_reply_that_is_not_one_vector_per_text_is_refused(google, fault):
    setattr(google, fault, True)
    with pytest.raises(EmbeddingsUnavailableError, match="Google did not return"):
        await embeddings._embed_google(["a", "b"])


@pytest.mark.asyncio
async def test_no_key_means_no_request(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    reset_settings()
    with pytest.raises(EmbeddingsUnavailableError, match="GOOGLE_API_KEY is not set"):
        await embeddings._embed_google(["x"])
    reset_settings()
