"""Keyword (BM25-style) search vectors, so Qdrant can match exact words as well as meaning.

A dense embedding finds text that *means* the same thing but can blur exact terms: a deal name, an
abbreviation, an id. A sparse vector is the opposite: one number per word the text contains. We
build it here and let Qdrant do the rest:

- here, per chunk: the word weight is BM25's term-frequency part (`tf * (k1 + 1) / (tf + k1 * (1 - b
  + b * length / average_length))`), so a repeated word counts more, with diminishing returns, and a
  long chunk does not win just by being long;
- in Qdrant: the collection's `bm25` vector has the IDF modifier, which multiplies each word by how
  rare it is across all chunks, so rare words count most. TF here times IDF there is BM25.

Words are turned into numbers with a stable hash (`crc32`), so the same word always gets the same
index, across runs and across machines. Two different words can collide on one index; with a 32-bit
space and a small corpus this is rare and only blurs, never breaks, the scoring.
"""

import re
import zlib
from collections import Counter

from qdrant_client.models import SparseVector

# BM25 constants. k1: how fast repeats stop helping. b: how strongly length is corrected.
K1 = 1.2
B = 0.75
# A 600-character chunk (app/rag/chunking.py) holds about 100 words.
AVERAGE_CHUNK_WORDS = 100

_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lower-cased words and numbers; punctuation is dropped."""
    return _WORD.findall(text.lower())


def term_index(term: str) -> int:
    """The word's slot in the sparse vector (a stable 32-bit hash)."""
    return zlib.crc32(term.encode()) & 0xFFFFFFFF


def document_vector(text: str) -> SparseVector:
    """The sparse vector stored with a chunk: BM25 term-frequency weights."""
    words = tokenize(text)
    length = len(words)
    weights: dict[int, float] = {}
    for term, count in Counter(words).items():
        weight = count * (K1 + 1) / (count + K1 * (1 - B + B * length / AVERAGE_CHUNK_WORDS))
        index = term_index(term)
        weights[index] = weights.get(index, 0.0) + weight
    return SparseVector(indices=list(weights), values=list(weights.values()))


def query_vector(text: str) -> SparseVector:
    """The sparse vector for a question: each distinct word once, weight 1."""
    indices = sorted({term_index(term) for term in tokenize(text)})
    return SparseVector(indices=indices, values=[1.0] * len(indices))
