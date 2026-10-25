"""Explicit chunking policy for ingestion (ported from apps/api/src/rag/chunking.ts).

Splitting a document into overlapping windows keeps each chunk small enough
for accurate embeddings while overlap avoids losing meaning that spans a
chunk boundary. Sizes are in characters, not tokens, to keep the logic simple
and dependency-free while learning the pipeline end to end.
"""

from dataclasses import dataclass

# Chunking: documents are cut into ~600-char pieces (100 overlap) so each piece gets its own embedding
CHUNK_SIZE = 600
CHUNK_OVERLAP = 100


@dataclass(frozen=True)
class Chunk:
    index: int
    content: str
    char_start: int
    char_end: int


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size.")

    trimmed = text.strip()
    if len(trimmed) == 0:
        return []

    chunks: list[Chunk] = []
    step = chunk_size - overlap
    start = 0
    index = 0

    while start < len(trimmed):
        end = min(start + chunk_size, len(trimmed))
        content = trimmed[start:end].strip()
        if len(content) > 0:
            chunks.append(Chunk(index=index, content=content, char_start=start, char_end=end))
            index += 1
        if end == len(trimmed):
            break
        start += step

    return chunks
