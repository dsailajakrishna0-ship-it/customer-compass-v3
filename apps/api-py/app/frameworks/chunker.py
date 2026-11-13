"""Stage 5.5, seam 1: the chunker, written with LangChain's `RecursiveCharacterTextSplitter`.

Same signature and same result type as `app.rag.chunking.chunk_text_manual`, so ingestion cannot tell the
two apart. The splitter cuts at the largest separator that keeps a piece under the size (blank line, then
line break, then space, then single characters), so chunks tend to end at paragraph or sentence edges
instead of at a fixed character count. Our character offsets come from its `add_start_index` option.
"""

from __future__ import annotations

from app.frameworks import require
from app.rag.chunking import CHUNK_OVERLAP, CHUNK_SIZE, Chunk


def chunk_text_frameworks(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size.")
    trimmed = text.strip()
    if len(trimmed) == 0:
        return []

    splitter_module = require("langchain_text_splitters")
    splitter = splitter_module.RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        add_start_index=True,  # the character offset of each chunk in `trimmed`
        strip_whitespace=True,
    )
    chunks: list[Chunk] = []
    for document in splitter.create_documents([trimmed]):
        content = document.page_content.strip()
        if not content:
            continue
        start = int(document.metadata["start_index"])
        chunks.append(
            Chunk(
                index=len(chunks), content=content, char_start=start, char_end=start + len(content)
            )
        )
    return chunks
