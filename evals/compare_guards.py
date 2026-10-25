"""Stage 8.d: compares guard strategies on the Stage 8.a adversarial set.

Run from apps/api-py:  uv run python ../../evals/compare_guards.py [--llm]

Always measures the regex rules (offline). With --llm it also runs the LLM
classifier (needs Ollama, or GUARD_PROVIDER=cloud + OPENROUTER_API_KEY) and the
combined rules+classifier mode. NeMo Guardrails and Guardrails AI are not
measured here.
"""

import asyncio
import json
import sys
from pathlib import Path

from app.guardrails import llm_guard

CASES = json.loads((Path(__file__).parent / "adversarial-prompts.json").read_text())


async def _flags(mode: str) -> list[bool]:
    return [bool((await llm_guard.guard_input(c["prompt"], mode)).matched_patterns) for c in CASES]


def _report(mode: str, flags: list[bool]) -> None:
    tp = sum(f and c["is_attack"] for f, c in zip(flags, CASES))
    fp = sum(f and not c["is_attack"] for f, c in zip(flags, CASES))
    attacks = sum(c["is_attack"] for c in CASES)
    missed = [c["id"] for f, c in zip(flags, CASES) if c["is_attack"] and not f]
    print(f"{mode:6} recall {tp}/{attacks}  false positives {fp}  missed: {', '.join(missed) or '-'}")


async def main() -> None:
    modes = ["rules", "llm", "both"] if "--llm" in sys.argv else ["rules"]
    for mode in modes:
        _report(mode, await _flags(mode))


asyncio.run(main())
