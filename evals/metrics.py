"""Pure scoring functions for the V3 evaluation baseline (no network, no models)."""

from __future__ import annotations

import math


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


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q from 0 to 100): the smallest value with at least q% of the data at or below it."""
    if not values:
        raise ValueError("percentile needs at least one value")
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def round_up_to(value: float, step: float) -> float:
    return math.ceil(value / step) * step
