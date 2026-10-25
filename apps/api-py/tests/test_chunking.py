"""Pure unit tests for the chunking policy (ported from
apps/api/src/rag/chunking.test.ts) — no network/database required."""

import pytest

from app.rag.chunking import chunk_text


def test_returns_no_chunks_for_empty_input() -> None:
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_returns_a_single_chunk_when_text_fits_within_chunk_size() -> None:
    chunks = chunk_text("short text", chunk_size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0].content == "short text"
    assert chunks[0].index == 0


def test_splits_long_text_into_overlapping_chunks_with_increasing_indexes() -> None:
    text = "a" * 250
    chunks = chunk_text(text, chunk_size=100, overlap=20)

    assert len(chunks) > 1
    for i, chunk in enumerate(chunks):
        assert chunk.index == i
    # Overlap means consecutive chunks share characters at the boundary.
    for i in range(1, len(chunks)):
        assert chunks[i].char_start < chunks[i - 1].char_end


def test_rejects_an_overlap_that_is_not_smaller_than_chunk_size() -> None:
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=10, overlap=10)
