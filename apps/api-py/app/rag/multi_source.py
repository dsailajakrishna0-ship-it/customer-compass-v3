"""Deciding where to search when there is more than one knowledge base (a Python-edition extension,
E1.2, ADR 0030; not part of the API contract shared with the Java edition).

Two of the three strategies of `POST /chat/multi` live here, because they are plain functions of a
question and the knowledge bases:

- **route**: a router model reads each knowledge base's description and says which ones can answer. A
  router can be wrong, so its failure mode matters: an answer that cannot be read means "search
  everything", never "search nothing". An explicit empty list is respected (nothing can answer).
- **all**: search every knowledge base with its own retriever (concurrently) and merge the results by
  rank. Scores from different corpora are not comparable, so the lists are merged by reciprocal rank
  fusion, which uses positions only; with a reranker configured it then orders the merged candidates.

The third strategy (the model picks through a tool) is a loop with the model, so it is a cycle in the
graph in `app/routes/multi_chat.py`.
"""

import asyncio
import json
import logging
from dataclasses import dataclass

from app.config import get_settings
from app.llm.gateway import generate
from app.rag.knowledge_bases import KnowledgeBase, search_knowledge_base
from app.rag.rerank import rerank_order, reranking_enabled
from app.rag.retrieve import RetrievedChunk, rrf_fuse

logger = logging.getLogger("app.rag.multi_source")

TOP_K = 4

ROUTER_SYSTEM_PROMPT = """You decide which knowledge bases to search for a user's question.
Knowledge bases:
{listing}

Reply with JSON only, no other text:
{{"knowledge_bases": ["<id>", ...], "reason": "<one short sentence>"}}
Choose every knowledge base that could hold the answer. Choose [] only when none can."""

UNREADABLE_REASON = "The router's answer could not be read; every knowledge base is searched."


@dataclass(frozen=True)
class KbChunk:
    """A retrieved chunk and the knowledge base it came from."""

    knowledge_base: str
    chunk: RetrievedChunk

    @property
    def key(self) -> str:
        """Unique across knowledge bases (chunk ids are only unique inside one)."""
        return f"{self.knowledge_base}:{self.chunk.chunk_id}"


@dataclass(frozen=True)
class Route:
    """Where the router sent a question: the ids to search, and why."""

    ids: list[str]
    reason: str
    fell_back: bool = False


def listing(knowledge_bases: list[KnowledgeBase]) -> str:
    return "\n".join(f"- {kb.id}: {kb.description}" for kb in knowledge_bases)


def parse_route(reply: str, known: list[str]) -> Route:
    """Reads the router's JSON; anything unusable means "search everything".

    Text and code fences around the object are ignored; duplicates and invented ids are dropped. A
    reply made only of invented ids is unusable (the router did not understand the task), but an
    explicit empty list is an answer: no knowledge base can answer this."""
    try:
        start, end = reply.find("{"), reply.rfind("}")
        if start < 0 or end < start:
            raise ValueError("no JSON object")
        data = json.loads(reply[start : end + 1])
        ids = data.get("knowledge_bases") if isinstance(data, dict) else None
        if not isinstance(ids, list):
            raise ValueError("no knowledge_bases list")
        chosen: list[str] = []
        for item in ids:
            if isinstance(item, str) and item in known and item not in chosen:
                chosen.append(item)
        if not chosen and ids:
            raise ValueError("only unknown ids")
        reason = data.get("reason")
        return Route(chosen, reason if isinstance(reason, str) else "")
    except (ValueError, TypeError) as exc:
        logger.warning("router_unreadable error=%s", type(exc).__name__)
        return Route(list(known), UNREADABLE_REASON, fell_back=True)


async def route_question(
    question: str, knowledge_bases: list[KnowledgeBase], model: str | None
) -> Route:
    """One model call: which knowledge bases can answer this question, from their descriptions?"""
    result = await generate(
        ROUTER_SYSTEM_PROMPT.format(listing=listing(knowledge_bases)),
        [{"role": "user", "content": question}],
        model,
    )
    return parse_route(result.content, [kb.id for kb in knowledge_bases])


async def merge(question: str, lists: list[list[KbChunk]], top_k: int) -> list[KbChunk]:
    """Merges per-knowledge-base results by rank (reciprocal rank fusion), then lets the optional
    reranker order the merged candidates by how well they fit the question."""
    by_key: dict[str, KbChunk] = {}
    for chunks in lists:
        for c in chunks:
            by_key.setdefault(c.key, c)
    order = rrf_fuse([[c.key for c in chunks] for chunks in lists], get_settings().rrf_k)
    merged = [by_key[key] for key in order]
    if reranking_enabled() and len(merged) > 1:
        texts = [f"{c.chunk.document_title}: {c.chunk.content}" for c in merged]
        ranked = await rerank_order(question, texts, top_k)
        if ranked is not None:
            return [merged[i] for i in ranked]
    return merged[:top_k]


async def search_all(
    question: str, knowledge_bases: list[KnowledgeBase], top_k: int = TOP_K
) -> list[KbChunk]:
    """Searches each knowledge base with its own retriever (each applies its own similarity floor, and
    hybrid search if switched on) and merges the results. The searches run concurrently: each task
    carries its own copy of the context variable that aims the retriever (ADR 0029), so they cannot
    cross."""
    found = await asyncio.gather(
        *(search_knowledge_base(kb, question, top_k) for kb in knowledge_bases)
    )
    lists = [
        [KbChunk(kb.id, chunk) for chunk in chunks]
        for kb, chunks in zip(knowledge_bases, found, strict=True)
    ]
    return await merge(question, lists, top_k)
