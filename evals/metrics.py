"""Pure scoring functions for the V3 evaluation baseline (no network, no models)."""

from __future__ import annotations


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Share of the relevant documents found in the first k results."""
    if not relevant:
        raise ValueError("recall needs at least one relevant document")
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    """1 / rank of the first relevant result, 0 if none was returned."""
    for position, doc in enumerate(ranked, start=1):
        if doc in relevant:
            return 1 / position
    return 0.0


def dedupe_keep_order(items: list[str]) -> list[str]:
    """Several chunks can come from one document; a document counts once, at its best rank."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def rate(flags: list[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


def within_tolerance(baseline: float, current: float, tolerance: float) -> bool:
    return abs(current - baseline) <= tolerance + 1e-9
