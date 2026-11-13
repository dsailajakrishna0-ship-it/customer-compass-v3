"""Stage 5.4: measure agentic retrieval against plain hybrid search, with record-and-replay.

This file has NO dependency on the API code or on the network in replay mode (`compare_agentic.py` passes
the app's own prompts and functions in), so the metrics, the caches and the table are unit-tested offline.

How the table stays reproducible (the same idea as the 5.2 judge cache and the 5.3 verdict cache):
- Every model call (the relevance check, the query rewrite, the answer, the grounding check) is stored in
  `agentic/cache.jsonl`, keyed by sha256(role, model, version, system prompt, user message), with the
  tokens it used and how long it took.
- Every search is stored in `agentic/snapshots.json`, keyed by the query, the company and the number of
  results, with the chunks it returned and how long it took. It needs Qdrant and Google embeddings to make
  one; replaying one needs nothing.
- In `replay` mode nothing but these two files is read: a missing entry stops the run (`ReplayMiss`). In
  `record` mode a missing entry is computed once and saved.
- Latencies in the table are the ones recorded when each call or search was made.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

EVALS = Path(__file__).resolve().parent
CACHE_FILE = EVALS / "agentic" / "cache.jsonl"
SNAPSHOT_FILE = EVALS / "agentic" / "snapshots.json"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_ATTEMPTS = 4

# ---- the pins -------------------------------------------------------------------------------
# Pinned 2026-11-13. The free models allow 50 requests a day in total and this comparison makes several
# hundred calls, so every model-backed step (checks and answers, in both arms) uses one small paid model.
# Prices from OpenRouter's model list on 2026-11-13, in US dollars per million tokens.
MODEL = "meta-llama/llama-3.1-8b-instruct"
PRICE_IN_PER_M = 0.02
PRICE_OUT_PER_M = 0.04
# The app's PROMPT_VERSION (app/rag/agentic.py) plus the answer prompt's version; bump to re-record.
VERSION = "agentic-v2/answer-v1"


class ReplayMiss(RuntimeError):
    """Replay mode needed a recorded call or search that does not exist."""


class RecordFailed(RuntimeError):
    """A call kept failing while recording; what was recorded so far is kept."""


def cache_key(role: str, model: str, version: str, system: str, user: str) -> str:
    digest = hashlib.sha256()
    for part in (role, model, version, system, user):
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def snapshot_key(query: str, company: str | None, top_k: int, mode: str) -> str:
    digest = hashlib.sha256()
    for part in (query, company or "", str(top_k), mode):
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


# ---- the call cache -----------------------------------------------------------------------------
@dataclass
class Call:
    content: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class CallCache:
    """One JSON object per line. The hash field is `sha256`, not `key`: a 64-hex value in a field named
    "key" trips the secret scanner (gitleaks)."""

    def __init__(self, path: Path = CACHE_FILE) -> None:
        self.path = path
        self.entries: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.entries[row["sha256"]] = row

    def get(self, key: str) -> Call | None:
        row = self.entries.get(key)
        if row is None:
            return None
        return Call(row["content"], row["tokens_in"], row["tokens_out"], row["latency_ms"])

    def put(self, key: str, role: str, model: str, version: str, call: Call) -> None:
        row = {
            "sha256": key,
            "role": role,
            "model": model,
            "version": version,
            "content": call.content,
            "tokens_in": call.tokens_in,
            "tokens_out": call.tokens_out,
            "latency_ms": call.latency_ms,
        }
        self.entries[key] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


class Recorder:
    """Sends prompts to the pinned model through the cache.

    mode "replay": cache only, never the network. mode "record": cache first, OpenRouter on a miss."""

    def __init__(
        self,
        mode: str = "replay",
        cache: CallCache | None = None,
        api_key: str = "",
        post: Callable[..., httpx.Response] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        model: str = MODEL,
        version: str = VERSION,
    ) -> None:
        if mode not in ("replay", "record"):
            raise ValueError("mode must be 'replay' or 'record'")
        if mode == "record" and not api_key:
            raise ValueError("record mode needs OPENROUTER_API_KEY")
        self.mode = mode
        self.cache = cache if cache is not None else CallCache()
        self.model = model
        self.version = version
        self._api_key = api_key
        self._post = post or httpx.post
        self._sleep = sleep
        self.fresh_calls = 0

    def call(self, role: str, system: str, user: str) -> Call:
        key = cache_key(role, self.model, self.version, system, user)
        found = self.cache.get(key)
        if found is not None:
            return found
        if self.mode == "replay":
            raise ReplayMiss(
                f"no recorded {role} call for key {key[:12]}; re-record with "
                "`just eval-agentic-record` (needs OPENROUTER_API_KEY and the stack)"
            )
        made = self._call_openrouter(system, user)
        self.cache.put(key, role, self.model, self.version, made)
        self.fresh_calls += 1
        return made

    def _call_openrouter(self, system: str, user: str) -> Call:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last = "unknown"
        for attempt in range(MAX_ATTEMPTS):
            started = time.monotonic()
            try:
                reply = self._post(OPENROUTER_URL, json=body, headers=headers, timeout=120)
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            else:
                elapsed = round((time.monotonic() - started) * 1000)
                if reply.status_code == 200:
                    payload = reply.json()
                    text = _reply_text(payload)
                    if text:
                        usage = payload.get("usage") or {}
                        return Call(
                            text,
                            int(usage.get("prompt_tokens") or 0),
                            int(usage.get("completion_tokens") or 0),
                            elapsed,
                        )
                    last = "empty reply"
                else:
                    last = f"HTTP {reply.status_code}"
                    if reply.status_code not in (408, 429, 500, 502, 503, 504):
                        break
            self._sleep(min(30.0, 3.0 * (attempt + 1)))
        raise RecordFailed(f"{self.model} failed: {last}")


def _reply_text(payload: dict) -> str:
    try:
        return (payload["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


# ---- the search snapshots ------------------------------------------------------------------------
class SnapshotStore:
    """query -> the chunks a real search returned, and how long it took."""

    def __init__(self, path: Path = SNAPSHOT_FILE) -> None:
        self.path = path
        self.entries: dict[str, dict[str, Any]] = (
            json.loads(path.read_text()) if path.exists() else {}
        )

    def get(self, key: str) -> dict[str, Any] | None:
        return self.entries.get(key)

    def put(self, key: str, entry: dict[str, Any]) -> None:
        self.entries[key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=1, sort_keys=True) + "\n")


# ---- the metrics -----------------------------------------------------------------------------
CITATION = re.compile(r"\[(\d+)\]")
DECLINE_PHRASES = (
    "could not find",
    "couldn't find",
    "do not contain",
    "does not contain",
    "don't contain",
    "doesn't contain",
    "not contain",
    "no information",
    "not mentioned",
    "not provided",
    "cannot answer",
    "can't answer",
    "unable to find",
    "not enough information",
    "do not have",
    "does not say",
    "do not say",
)


def cited_numbers(answer: str, count: int) -> list[int]:
    """Zero-based positions of the sources an answer cites with [n], each once, in order of mention."""
    seen: list[int] = []
    for match in CITATION.finditer(answer):
        n = int(match.group(1)) - 1
        if 0 <= n < count and n not in seen:
            seen.append(n)
    return seen


def declined(answer: str, had_sources: bool) -> bool:
    """The answer says it cannot answer: no sources at all, or the usual wording of a refusal."""
    if not had_sources:
        return True
    lower = answer.lower()
    return any(phrase in lower for phrase in DECLINE_PHRASES)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q / 100 * len(ordered))) - 1]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def cost_usd(tokens_in: int, tokens_out: int) -> float:
    return tokens_in / 1e6 * PRICE_IN_PER_M + tokens_out / 1e6 * PRICE_OUT_PER_M


@dataclass
class CaseResult:
    """What one arm did for one question."""

    id: str
    answerable: bool
    ranked_docs: list[str]  # source files of the returned chunks, deduped, best first
    returned: int  # chunks the model was shown
    answer: str
    declined: bool
    grounded: bool | None  # None: no sources to check
    citations_total: int
    citations_correct: int
    latency_ms: int  # search + checks + answer, as recorded
    tokens_in: int
    tokens_out: int
    llm_calls: int  # every model call for this question, answer included
    extra_calls: int  # the calls the agentic layer added (checks, rewrite, grounding)
    rewritten: bool = False
    fell_back: bool = False
    metrics: dict[str, float] = field(default_factory=dict)


def recall_at(ranked: list[str], relevant: set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for position, doc in enumerate(ranked, start=1):
        if doc in relevant:
            return 1 / position
    return 0.0


def summarise(results: list[CaseResult]) -> dict[str, Any]:
    """One arm's table row: retrieval, citations, answer behaviour, grounding, latency and cost."""
    answerable = [r for r in results if r.answerable]
    unanswerable = [r for r in results if not r.answerable]
    with_answer = [r for r in results if r.grounded is not None]
    citations = sum(r.citations_total for r in answerable)
    latencies = [float(r.latency_ms) for r in results]
    tokens_in = sum(r.tokens_in for r in results)
    tokens_out = sum(r.tokens_out for r in results)
    return {
        "cases": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "recall_at_1": round(mean([r.metrics["recall_at_1"] for r in answerable]), 3),
        "recall_at_3": round(mean([r.metrics["recall_at_3"] for r in answerable]), 3),
        "recall_at_4": round(mean([r.metrics["recall_at_4"] for r in answerable]), 3),
        "mrr": round(mean([r.metrics["mrr"] for r in answerable]), 3),
        "chunks_shown": round(mean([float(r.returned) for r in results]), 2),
        "citation_correctness": round(sum(r.citations_correct for r in answerable) / citations, 3)
        if citations
        else None,
        "answerable_answered": sum(1 for r in answerable if not r.declined),
        "unanswerable_declined": sum(1 for r in unanswerable if r.declined),
        "grounded": sum(1 for r in with_answer if r.grounded),
        "answers_checked": len(with_answer),
        "median_ms": round(percentile(latencies, 50)),
        "p95_ms": round(percentile(latencies, 95)),
        "mean_ms": round(mean(latencies)),
        "llm_calls_per_question": round(mean([float(r.llm_calls) for r in results]), 2),
        "extra_calls_per_question": round(mean([float(r.extra_calls) for r in results]), 2),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost_usd(tokens_in, tokens_out), 5),
        "rewritten": sum(1 for r in results if r.rewritten),
        "fell_back": sum(1 for r in results if r.fell_back),
    }


# Counts are exact in replay; floats get a hair of slack for rounding.
TOLERANCE = 0.0005


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Messages for numbers that moved against the baseline (empty means a pass)."""
    problems: list[str] = []
    for arm, base_row in baseline.items():
        row = current.get(arm)
        if row is None:
            problems.append(f"{arm}: missing from this run")
            continue
        for name, base in base_row.items():
            now = row.get(name)
            if isinstance(base, (int, float)) and isinstance(now, (int, float)):
                if abs(now - base) > TOLERANCE:
                    problems.append(f"{arm}.{name}: {now} vs baseline {base}")
            elif now != base:
                problems.append(f"{arm}.{name}: {now} vs baseline {base}")
    return problems


ROWS = (
    ("recall@1 (answerable)", "recall_at_1", "{:.3f}"),
    ("recall@3", "recall_at_3", "{:.3f}"),
    ("recall@4 (all shown)", "recall_at_4", "{:.3f}"),
    ("MRR", "mrr", "{:.3f}"),
    ("citation correctness", "citation_correctness", "{:.3f}"),
    ("answerable questions answered", "answerable_answered", "{}"),
    ("unanswerable declined", "unanswerable_declined", "{}"),
    ("answers grounded (own check)", "grounded", "{}"),
    ("chunks shown per question", "chunks_shown", "{:.2f}"),
    ("median ms per question", "median_ms", "{}"),
    ("p95 ms per question", "p95_ms", "{}"),
    ("model calls per question", "llm_calls_per_question", "{:.2f}"),
    ("extra calls from the layer", "extra_calls_per_question", "{:.2f}"),
    ("tokens in", "tokens_in", "{}"),
    ("tokens out", "tokens_out", "{}"),
    ("cost, whole run (USD)", "cost_usd", "{:.4f}"),
    ("queries rewritten", "rewritten", "{}"),
    ("checks that fell back", "fell_back", "{}"),
)


def format_table(summaries: dict[str, dict[str, Any]], header: str) -> str:
    plain, agentic = summaries["plain"], summaries["agentic"]
    lines = [header, "", f"{'':<32}{'plain hybrid':>14}{'agentic':>12}"]
    for label, key, fmt in ROWS:
        a, b = plain.get(key), agentic.get(key)
        lines.append(
            f"{label:<32}{(fmt.format(a) if a is not None else '-'):>14}"
            f"{(fmt.format(b) if b is not None else '-'):>12}"
        )
    lines.append(
        f"\nanswerable {plain['answerable']}, unanswerable {plain['unanswerable']}; "
        f"grounded counts are out of {plain['answers_checked']} (plain) and "
        f"{agentic['answers_checked']} (agentic) answers that had sources"
    )
    return "\n".join(lines)


Retrieve = Callable[[str, str | None, int], Awaitable[list[Any]]]
