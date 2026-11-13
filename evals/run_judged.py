"""Stage 5.2: LLM-judged answer quality for the RAG chat, one metrics table per run.

    just eval-judged            replay the recorded judge answers (offline, free, deterministic)
    just eval-judged-record     call the pinned free judge on OpenRouter for anything not recorded yet

What is judged: for each case in golden/judged.json, the answer and the retrieved snippets recorded in
judged/subjects.json (taken from `POST /api/v1/chat/rag`). The judge (DeepEval metrics running on the
pinned model in judge.py) scores faithfulness, answer relevancy, context precision and context recall.
The table puts the run next to baseline/judged-v1.json, with the V2 retrieval numbers underneath.

Exit code: 0 pass, 1 a metric moved more than the tolerance (with --check), 2 a case could not be
scored (replay miss, rate limit, bad JSON from the judge).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS))
import judge as judge_lib  # noqa: E402

GOLDEN = EVALS / "golden" / "judged.json"
SUBJECTS = EVALS / "judged" / "subjects.json"
RUNS = EVALS / "runs"
JUDGED_BASELINE = EVALS / "baseline" / "judged-v1.json"
V2_BASELINE = EVALS / "baseline" / "v2.json"


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, cwd=EVALS
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def branch_and_sha() -> tuple[str, str]:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("", "HEAD"):  # detached, as in CI
        branch = (
            os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME") or "detached"
        )
    return branch, _git("rev-parse", "--short", "HEAD") or "unknown"


def load_subjects() -> dict:
    return json.loads(SUBJECTS.read_text()) if SUBJECTS.exists() else {}


def record_subjects(cases: list[dict], api_url: str, refresh: bool) -> dict:
    """Ask the running API once per case and keep the answer and snippets, so judging can be replayed."""
    subjects = load_subjects()
    for case in cases:
        if case["id"] in subjects and not refresh:
            continue
        reply = httpx.post(
            f"{api_url}/api/v1/chat/rag", json={"messages": [{"role": "user", "content": case["question"]}]},
            timeout=120,
        )
        reply.raise_for_status()
        body = reply.json()
        subjects[case["id"]] = {
            "question": case["question"],
            "answer": body["message"],
            "contexts": [c["snippet"] for c in body.get("citations", [])],
            "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
    SUBJECTS.parent.mkdir(parents=True, exist_ok=True)
    SUBJECTS.write_text(json.dumps(subjects, indent=2, sort_keys=True) + "\n")
    return subjects


def judge_cases(cases: list[dict], subjects: dict, judge: judge_lib.Judge, scorer) -> list[dict]:
    results = []
    stop: str | None = None
    for case in cases:
        row: dict = {"id": case["id"], "scores": {}}
        subject = subjects.get(case["id"])
        if stop:
            row["error"] = stop
        elif not subject:
            row["error"] = "no recorded answer for this case (run `just eval-judged-record`)"
        elif not subject["contexts"]:
            row["error"] = "the answer had no retrieved context to judge"
        else:
            try:
                row["scores"] = scorer(judge, {**case, **subject})
            except judge_lib.JudgeUnavailable as exc:
                row["error"] = stop = f"{exc}; remaining cases skipped (re-run to resume)"
            except Exception as exc:  # noqa: BLE001 - one bad judge reply must not hide the others
                row["error"] = f"{type(exc).__name__}: {exc}"
        results.append(row)
    return results


def build_report(cases: list[dict], results: list[dict], judge: judge_lib.Judge, mode: str) -> dict:
    branch, sha = branch_and_sha()
    return {
        "schema": 1,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "branch": branch,
        "git_sha": sha,
        "mode": mode,
        "judge": {"model": judge.model, "prompt_version": judge.prompt_version},
        "judge_calls": {"total": len(judge.calls), "fresh": judge.fresh_calls},
        "metrics": judge_lib.summarise(results),
        "cases": results,
        "raw_judge_calls": judge.calls,  # every prompt and raw reply of this run
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=("replay", "record"), default="replay")
    parser.add_argument("--check", action="store_true", help="compare with baseline/judged-v1.json")
    parser.add_argument(
        "--save-baseline", action="store_true", help="write baseline/judged-v1.json"
    )
    parser.add_argument(
        "--refresh-subjects", action="store_true", help="re-ask the API (record mode)"
    )
    parser.add_argument("--api-url", default=os.environ.get("API_URL", "http://localhost:8001"))
    args = parser.parse_args(argv)

    cases = json.loads(GOLDEN.read_text())
    subjects = (
        record_subjects(cases, args.api_url, args.refresh_subjects)
        if args.mode == "record"
        else load_subjects()
    )
    judge = judge_lib.Judge(mode=args.mode, api_key=os.environ.get("OPENROUTER_API_KEY", ""))
    import deepeval_adapter  # imported late: only this path needs DeepEval installed

    results = judge_cases(cases, subjects, judge, deepeval_adapter.score_case)
    report = build_report(cases, results, judge, args.mode)

    RUNS.mkdir(exist_ok=True)
    stamp = report["date"].replace(":", "").replace("-", "")[:15]
    out = RUNS / f"judged-{stamp}-{report['git_sha']}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")

    baseline = (
        json.loads(JUDGED_BASELINE.read_text())["metrics"] if JUDGED_BASELINE.exists() else None
    )
    v2 = None
    if V2_BASELINE.exists():
        v2 = (
            json.loads(V2_BASELINE.read_text())
            .get("suites", {})
            .get("retrieval", {})
            .get("metrics")
        )
    header = (
        f"judged evals  branch {report['branch']} @ {report['git_sha']}  [{args.mode}]\n"
        f"judge {judge.model}  prompts {judge.prompt_version}  "
        f"calls {report['judge_calls']['total']} ({report['judge_calls']['fresh']} fresh)"
    )
    print(judge_lib.format_table(report["metrics"], baseline, v2, header))
    print(f"\nraw judge outputs: {out.relative_to(EVALS.parent)}")

    errored = [r for r in results if r.get("error")]
    if args.save_baseline and errored:
        print("baseline NOT written: some cases were not scored (re-run to resume, then save)")
    elif args.save_baseline:
        JUDGED_BASELINE.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "date": report["date"][:10],
                    "git_sha": report["git_sha"],
                    "judge": report["judge"],
                    "metrics": report["metrics"],
                },
                indent=2,
            )
            + "\n"
        )
        print(f"baseline written: {JUDGED_BASELINE.relative_to(EVALS.parent)}")

    for row in errored:
        print(f"ERROR {row['id']}: {row['error']}")
    if errored:
        return 2
    if args.check and baseline:
        problems = judge_lib.compare(baseline, report["metrics"])
        for problem in problems:
            print(f"REGRESSION {problem}")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
