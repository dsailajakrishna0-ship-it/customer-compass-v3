"""Stage 5.2: the pinned LLM judge, its record-and-replay cache, and the judged-metrics report.

This file has NO dependency on DeepEval (that lives in `deepeval_adapter.py` and is only installed
for `just eval-judged`), so everything here is unit-tested offline in CI.

How the judge stays reproducible:
- The judge model and the prompt version are pinned below. Changing either gives every call a new
  cache key, so an old recording can never be mistaken for a new judgement.
- Every call is keyed by sha256(model, prompt version, prompt). In `replay` mode the network is never
  touched: a missing key stops the run (`ReplayMiss`). In `record` mode a missing key is sent to
  OpenRouter once, then saved, so the next run is free, fast and gives identical numbers.
- The raw answer of every call (cached or fresh) goes into one JSON file per run (`evals/runs/`).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

# ---- the pins -------------------------------------------------------------------------------
# Pinned 2026-11-13. The Gemma free models answered HTTP 429 (shared upstream pool) all that day, so the
# judge is NVIDIA Nemotron 3 Nano; a different model from the one that writes the answers (liquid LFM).
JUDGE_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
# DeepEval writes the prompts, so its version is part of the prompt version. Bump this string (and
# re-record) whenever deepeval, the JSON instruction below or the judge settings change.
JUDGE_PROMPT_VERSION = "deepeval-4.3.4/json-v1"
JSON_INSTRUCTION = (
    "\n\nReply with ONE valid JSON object only, matching the format requested above. "
    "No markdown fences, no commentary."
)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MIN_SECONDS_BETWEEN_CALLS = 4.0  # stays under the free tier's 20 requests per minute
MAX_ATTEMPTS = 4

CACHE_FILE = Path(__file__).resolve().parent / "judged" / "cache.jsonl"


class ReplayMiss(RuntimeError):
    """Replay mode needed a judge answer that was never recorded."""


class JudgeUnavailable(RuntimeError):
    """The hosted judge kept failing (rate limit, outage); nothing was recorded for this call."""


def cache_key(model: str, prompt_version: str, prompt: str) -> str:
    digest = hashlib.sha256()
    for part in (model, prompt_version, prompt):
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


class JudgeCache:
    """One JSON object per line: {key, model, prompt_version, response}. Only hashes and answers are
    stored (the prompts contain answer text and are kept in the per-run file instead)."""

    def __init__(self, path: Path = CACHE_FILE) -> None:
        self.path = path
        self.entries: dict[str, dict[str, str]] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.entries[row["key"]] = row

    def get(self, key: str) -> str | None:
        row = self.entries.get(key)
        return row["response"] if row else None

    def put(self, key: str, model: str, prompt_version: str, response: str) -> None:
        row = {"key": key, "model": model, "prompt_version": prompt_version, "response": response}
        self.entries[key] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


# ---- reading the judge's answer -------------------------------------------------------------
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> Any:
    """The first JSON object in a model reply. Small models wrap JSON in fences or add a sentence."""
    cleaned = _FENCE.sub("", text.strip())
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("no JSON object in the judge reply")
    try:
        value, _end = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(f"the judge reply is not valid JSON: {exc.msg}") from exc
    return value


# ---- the judge -------------------------------------------------------------------------------
class Judge:
    """Sends prompts to the pinned model, through the cache.

    mode "replay": cache only, never the network (CI, and every repeat run).
    mode "record": cache first, OpenRouter on a miss, then save the answer.
    """

    def __init__(
        self,
        mode: str = "replay",
        cache: JudgeCache | None = None,
        api_key: str = "",
        post: Callable[..., httpx.Response] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        model: str = JUDGE_MODEL,
        prompt_version: str = JUDGE_PROMPT_VERSION,
    ) -> None:
        if mode not in ("replay", "record"):
            raise ValueError("mode must be 'replay' or 'record'")
        if mode == "record" and not api_key:
            raise ValueError("record mode needs OPENROUTER_API_KEY")
        self.mode = mode
        self.cache = cache if cache is not None else JudgeCache()
        self.model = model
        self.prompt_version = prompt_version
        self._api_key = api_key
        self._post = post or httpx.post
        self._sleep = sleep
        self._last_call = 0.0
        self.calls: list[dict[str, Any]] = []  # the raw per-run log

    def complete(self, prompt: str) -> str:
        full_prompt = prompt + JSON_INSTRUCTION
        key = cache_key(self.model, self.prompt_version, full_prompt)
        response = self.cache.get(key)
        cached = response is not None
        if response is None:
            if self.mode == "replay":
                raise ReplayMiss(
                    f"no recorded judge answer for key {key[:12]}; re-record with "
                    "`just eval-judged-record` (needs OPENROUTER_API_KEY)"
                )
            response = self._call_openrouter(full_prompt)
            self.cache.put(key, self.model, self.prompt_version, response)
        self.calls.append(
            {"key": key, "cached": cached, "prompt": full_prompt, "response": response}
        )
        return response

    def _call_openrouter(self, prompt: str) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_error = "unknown"
        for attempt in range(MAX_ATTEMPTS):
            wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()
            try:
                reply = self._post(OPENROUTER_URL, json=body, headers=headers, timeout=120)
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
            else:
                if reply.status_code == 200:
                    text = _reply_text(reply.json())
                    if text:
                        return text
                    last_error = "empty reply"
                else:
                    last_error = f"HTTP {reply.status_code}"
                    if "free-models-per-day" in reply.text:
                        # Waiting would not help: the free tier allows 50 requests a day (resets 00:00 UTC)
                        raise JudgeUnavailable(
                            "daily free-model limit reached (50 requests a day on OpenRouter's free "
                            "tier, resets at 00:00 UTC); what was recorded so far is kept"
                        )
                    if reply.status_code not in (408, 429, 500, 502, 503, 504):
                        break
            self._sleep(min(60.0, 10.0 * (attempt + 1)))
        raise JudgeUnavailable(f"judge {self.model} failed: {last_error}")

    @property
    def fresh_calls(self) -> int:
        return sum(1 for call in self.calls if not call["cached"])


def _reply_text(payload: dict) -> str:
    try:
        return (payload["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


# ---- the report ------------------------------------------------------------------------------
METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
# The judge is a small free model, so its scores wobble more than retrieval maths does.
TOLERANCE = 0.15


def summarise(cases: list[dict]) -> dict[str, float | int | None]:
    """Mean of each metric over the cases that scored it; errored cases are left out and counted."""
    out: dict[str, float | int | None] = {"cases": len(cases)}
    for name in METRICS:
        scores = [c["scores"][name] for c in cases if c.get("scores", {}).get(name) is not None]
        out[name] = round(sum(scores) / len(scores), 3) if scores else None
    out["errored_cases"] = sum(1 for c in cases if c.get("error"))
    return out


def compare(baseline: dict, current: dict, tolerance: float = TOLERANCE) -> list[str]:
    """Messages for judged metrics that moved by more than the tolerance (empty means a pass)."""
    problems = []
    for name in METRICS:
        base, now = baseline.get(name), current.get(name)
        if base is None:
            continue
        if now is None:
            problems.append(f"{name}: no score (baseline {base})")
        elif abs(now - base) > tolerance:
            problems.append(f"{name}: {now} vs baseline {base} (allowed +/-{tolerance})")
    return problems


def format_table(
    current: dict, baseline: dict | None, v2_retrieval: dict | None, header: str
) -> str:
    """One metrics table for the run: judged metrics against the judged baseline, with the V2
    retrieval numbers (evals/baseline/v2.json) under it for context."""
    lines = [header, "", f"{'metric':<22}{'baseline':>10}{'this run':>10}{'delta':>9}"]
    for name in METRICS:
        base = (baseline or {}).get(name)
        now = current.get(name)
        delta = f"{now - base:+.3f}" if base is not None and now is not None else "-"
        lines.append(f"{name:<22}{_fmt(base):>10}{_fmt(now):>10}{delta:>9}")
    lines.append(f"{'cases scored':<22}{'':>10}{current['cases'] - current['errored_cases']:>10}")
    if v2_retrieval:
        lines += [
            "",
            "retrieval, from evals/baseline/v2.json (re-measure with `just eval-retrieval`)",
        ]
        for name in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr"):
            if name in v2_retrieval:
                lines.append(f"  {name:<20}{v2_retrieval[name]:>10}")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"
