"""Stage 5.3: the guard comparison table.

Run from the repo root (the `just` recipes do):

    just eval-guards            replay the recorded verdicts (offline, free, no keys, deterministic)
    just eval-guards-record     compute the verdicts that are missing from the cache
                                (needs OPENROUTER_API_KEY; NeMo Guardrails and Presidio are layered on)

Compared on 74 prompts (44 attacks, 30 benign) and 32 PII texts (20 with PII, 12 clean):
  - our rule-based guard (Stage 8), live,
  - our LLM classifier (`GUARD_MODE=llm`: its prompt and parser, from the app, on the pinned model),
  - rules + classifier (`GUARD_MODE=both`),
  - Llama Guard 4 (a safety classifier, hosted on OpenRouter),
  - NeMo Guardrails with its `self check input` rail,
  - Presidio for PII (and our rules and Llama Guard on the same PII texts).

Exit code: 0 ok, 1 a number moved against the baseline (with --check), 2 a verdict is missing in
replay mode or a strategy kept failing while recording.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS))
sys.path.insert(
    0, str(EVALS.parent / "apps" / "api-py")
)  # the app's own rules and classifier prompt
import guard_compare as g  # noqa: E402

BASELINE = EVALS / "baseline" / "guards-v1.json"
RUNS = EVALS / "runs"


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, cwd=EVALS
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _strategies(mode: str) -> dict[str, g.Strategy]:
    if mode == "replay":
        return {name: g.Replayed(name, model) for name, model in g.REPLAYED_MODELS.items()}
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        sys.exit("record mode needs OPENROUTER_API_KEY in the environment")
    try:
        from app.guardrails.llm_guard import CLASSIFIER_SYSTEM_PROMPT, parse_verdict

        nemo = g.NemoSelfCheck(api_key)
        presidio = g.PresidioScan()
    except ImportError as exc:
        sys.exit(
            f"{exc}. Record with `just eval-guards-record` (it layers NeMo Guardrails and Presidio on)."
        )
    return {
        "classifier": g.AppClassifier(CLASSIFIER_SYSTEM_PROMPT, parse_verdict, api_key=api_key),
        "llama_guard": g.LlamaGuard(api_key=api_key),
        "nemo": nemo,
        "presidio": presidio,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--mode", choices=("replay", "record"), default="replay")
    parser.add_argument(
        "--check", action="store_true", help="fail if a count differs from the baseline"
    )
    parser.add_argument(
        "--save-baseline", action="store_true", help="overwrite evals/baseline/guards-v1.json"
    )
    args = parser.parse_args()

    from app.guardrails.prompt_guard import scan_and_neutralize

    runner = g.Runner(g.VerdictCache(), args.mode)
    try:
        report = g.compare(
            runner,
            rules=lambda text: bool(scan_and_neutralize(text).matched_patterns),
            strategies=_strategies(args.mode),
        )
    except (g.ReplayMiss, g.RecordFailed) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 2

    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    sha = _git("rev-parse", "--short", "HEAD") or "unknown"
    print(f"Guard comparison  branch {branch}  commit {sha}  mode {args.mode}")
    print(g.render(report))

    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (RUNS / f"guards-{stamp}-{sha}.json").write_text(json.dumps(report, indent=2) + "\n")

    current = g.comparable(report)
    if args.save_baseline:
        BASELINE.write_text(json.dumps(current, indent=2) + "\n")
        print(f"baseline written to {BASELINE.relative_to(EVALS.parent)}")
    if args.check:
        diffs = g.differences(json.loads(BASELINE.read_text()), current)
        if diffs:
            print("\nCHECK FAILED against evals/baseline/guards-v1.json:")
            for line in diffs:
                print(f"  {line}")
            return 1
        print("\nCHECK OK: every count matches evals/baseline/guards-v1.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
