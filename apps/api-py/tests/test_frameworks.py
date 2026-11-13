"""Stage 5.5: the framework side of each seam, and the rules that keep it a drop-in.

Tests that need the optional packages (`evals/requirements-frameworks.txt`) skip themselves when they are
not installed, so the default `just test-api` stays green on a default install; `just test-frameworks`
installs them and runs these plus the whole contract suite with `AGENT_IMPL=frameworks`.
"""

import asyncio
import importlib

import pytest

from app.config import Settings, reset_settings
from app.frameworks import INSTALL_HINT, require
from app.rag.chunking import Chunk, chunk_text, chunk_text_manual
from app.rag.ingest import _with_framework_metadata

framework = pytest.mark.frameworks

SAMPLE = (
    "# Renewal call\n\nMaya asked about the renewal of the Premium Operations Plan. "
    "She wants onboarding for two more factory floors and a multi-site discount.\n\n"
    "## Pricing\n\nThe quote was 48,000 per year. Clause 7.3 sets sixty days of notice. "
    "Northstar asked the same question last quarter and got the same answer.\n\n"
) * 6


# ------------------------------------------------------------------ settings: nothing changes by default


def test_every_seam_defaults_to_manual(monkeypatch):
    for name in ("CHUNKER_IMPL", "RETRIEVAL_IMPL", "AGENT_IMPL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert (settings.chunker_impl, settings.retrieval_impl, settings.agent_impl) == (
        "manual",
        "manual",
        "manual",
    )


def test_a_wrong_impl_stops_start_up(monkeypatch):
    monkeypatch.setenv("AGENT_IMPL", "langchain")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_frameworks_retrieval_with_hybrid_search_is_refused_at_start_up(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_IMPL", "frameworks")
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    with pytest.raises(ValueError, match="dense only"):
        Settings(_env_file=None)


def test_the_default_chunker_is_ours_and_unchanged(monkeypatch):
    monkeypatch.delenv("CHUNKER_IMPL", raising=False)
    reset_settings()
    assert chunk_text(SAMPLE) == chunk_text_manual(SAMPLE)


def test_a_missing_optional_package_says_how_to_install_it(monkeypatch):
    real = importlib.import_module

    def broken(name, *args, **kwargs):
        if name == "langchain_text_splitters":
            raise ImportError("not installed")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", broken)
    with pytest.raises(RuntimeError, match="requirements-frameworks.txt"):
        require("langchain_text_splitters")
    assert "requirements-frameworks.txt" in INSTALL_HINT


# ------------------------------------------------------------------ ingestion payload


def test_ingestion_payload_is_unchanged_unless_the_framework_retriever_is_on(monkeypatch):
    payload = {"content": "text", "document_id": 1, "document_title": "T"}
    monkeypatch.delenv("RETRIEVAL_IMPL", raising=False)
    reset_settings()
    assert _with_framework_metadata(payload) == payload

    monkeypatch.setenv("RETRIEVAL_IMPL", "frameworks")
    reset_settings()
    assert _with_framework_metadata(payload) == {
        **payload,
        "metadata": {"document_id": 1, "document_title": "T"},
    }


# ------------------------------------------------------------------ seam 1: the chunker


@framework
class TestFrameworkChunker:
    @pytest.fixture(autouse=True)
    def langchain(self):
        pytest.importorskip("langchain_text_splitters")

    def chunks(self, text=SAMPLE, size=300, overlap=50):
        from app.frameworks.chunker import chunk_text_frameworks

        return chunk_text_frameworks(text, size, overlap)

    def test_the_result_type_and_indexes_are_the_same_as_ours(self):
        chunks = self.chunks()
        assert chunks and all(isinstance(c, Chunk) for c in chunks)
        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_no_chunk_is_longer_than_the_size(self):
        assert all(len(c.content) <= 300 for c in self.chunks())

    def test_offsets_point_at_the_chunk_in_the_trimmed_text(self):
        trimmed = SAMPLE.strip()
        for c in self.chunks():
            assert trimmed[c.char_start : c.char_end] == c.content

    def test_empty_text_and_bad_arguments_behave_like_ours(self):
        assert self.chunks("") == [] and self.chunks("   ") == []
        with pytest.raises(ValueError):
            self.chunks(size=10, overlap=10)
        with pytest.raises(ValueError):
            self.chunks(size=0)

    def test_short_text_is_one_chunk(self):
        [only] = self.chunks("short text", 100, 10)
        assert only.content == "short text" and only.index == 0

    def test_it_never_cuts_a_word_in_two_but_a_fixed_window_does(self):
        trimmed = SAMPLE.strip()

        def mid_word_cuts(chunks):
            return sum(
                c.char_end < len(trimmed)
                and trimmed[c.char_end - 1].isalnum()
                and trimmed[c.char_end].isalnum()
                for c in chunks
            )

        assert mid_word_cuts(self.chunks()) == 0
        assert mid_word_cuts(chunk_text_manual(SAMPLE, 300, 50)) > 0

    def test_the_setting_switches_the_side_behind_the_same_function(self, monkeypatch):
        monkeypatch.setenv("CHUNKER_IMPL", "frameworks")
        reset_settings()
        assert chunk_text(SAMPLE, 300, 50) == self.chunks()


# ------------------------------------------------------------------ seam 2: the retriever


@framework
class TestFrameworkRetriever:
    @pytest.fixture(autouse=True)
    def langchain(self):
        pytest.importorskip("langchain_qdrant")

    def test_a_hit_becomes_the_same_retrieved_chunk_our_code_builds(self):
        from langchain_core.documents import Document

        from app.frameworks.retriever import _chunk

        document = Document(
            page_content="Renewal notice is sixty days.",
            metadata={
                "_id": "abc",
                "document_id": 3,
                "document_title": "Contract",
                "source_path": "sample-data/documents/c.pdf",
                "doc_type": "pdf",
                "company_name": "Acme Fabrication",
                "chunk_index": 2,
                "page": 4,
            },
        )
        chunk = _chunk(document, 0.71)
        assert (chunk.chunk_id, chunk.document_id, chunk.similarity) == ("abc", 3, 0.71)
        assert (chunk.page, chunk.sheet, chunk.location) == (4, None, "page 4")
        assert chunk.content == "Renewal notice is sixty days."

    def test_the_embeddings_adapter_hands_the_async_call_back_to_the_running_loop(
        self, monkeypatch
    ):
        from app.frameworks import retriever

        async def fake_embed(text):
            return [float(len(text)), 1.0]

        monkeypatch.setattr(retriever, "embed_text", fake_embed)
        embeddings = retriever._embeddings_class()()

        async def from_a_worker_thread():
            embeddings.loop = asyncio.get_running_loop()
            return await asyncio.to_thread(embeddings.embed_query, "four")

        assert asyncio.run(from_a_worker_thread()) == [4.0, 1.0]

    def test_the_search_asks_for_the_raw_cosine_floor_not_a_rescaled_one(self, monkeypatch):
        from app.frameworks import retriever
        from app.rag.retrieve import MIN_SIMILARITY

        seen = {}

        class FakeStore:
            def similarity_search_with_score(self, question, **kwargs):
                seen.update(kwargs, question=question)
                return []

        async def count():
            return 5

        monkeypatch.setattr(retriever, "_store", lambda *_: (FakeStore(), retriever_embeddings()))
        monkeypatch.setattr(retriever, "get_point_count", count)

        def retriever_embeddings():
            return type("E", (), {"loop": None})()

        assert asyncio.run(retriever.dense_chunks("q", 7, 4)) == []
        assert seen["score_threshold"] == MIN_SIMILARITY and seen["k"] == 4
        assert seen["filter"] is not None  # company 7 plus company-agnostic documents


# ------------------------------------------------------------------ seam 3: the prebuilt agent


@framework
class TestFrameworkAgent:
    @pytest.fixture(autouse=True)
    def langchain(self):
        pytest.importorskip("langchain")

    def test_langchain_messages_become_the_plain_dicts_our_gateway_takes(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        from app.frameworks.agent import _to_openai_messages

        system, plain = _to_openai_messages(
            [
                SystemMessage("be brief"),
                HumanMessage("analyze Acme"),
                AIMessage(
                    "",
                    tool_calls=[{"id": "c1", "name": "search_documents", "args": {"query": "x"}}],
                ),
                ToolMessage("E1 [doc] text", tool_call_id="c1"),
            ]
        )
        assert system == "be brief"
        assert plain[0] == {"role": "user", "content": "analyze Acme"}
        assert plain[1]["tool_calls"][0]["function"] == {
            "name": "search_documents",
            "arguments": '{"query": "x"}',
        }
        assert plain[2] == {"role": "tool", "tool_call_id": "c1", "content": "E1 [doc] text"}

    def test_the_prebuilt_graph_keeps_the_same_state_and_shared_nodes(self):
        from app.agent import workflow
        from app.frameworks.agent import build_graph_frameworks

        manual, prebuilt = workflow.build_graph(), build_graph_frameworks()
        shared = {"classify", "review", "prepare_revision", "draft"}
        assert shared <= set(manual.get_graph().nodes) & set(prebuilt.get_graph().nodes)
        assert "research" in prebuilt.get_graph().nodes
        assert not {"evidence", "documents", "analyze"} & set(prebuilt.get_graph().nodes)
