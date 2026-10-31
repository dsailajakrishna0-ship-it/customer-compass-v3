"""V3 is cloud-only (ADR 0010): the local model runner must not creep back in.

Any tracked text file that mentions it fails this test, except the places that exist to discuss it:
history (the V2 record, decision records, the saved V2 baseline), the plan, and the Stage 1 guide."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORD = "ollama"

# Files or folders that may mention it, and why
ALLOWED = (
    "docs/adr/",  # decision records describe what was decided and removed
    "docs/v2-baseline/",  # the frozen V2 record
    "docs/recommendations-2.md",  # frozen V2-era recommendations
    "docs/roadmap.md",  # the plan names the removal
    "docs/tech-stack.md",  # records what V3 removed, plus the V2 stage history
    "docs/stages/01-model-layer.md",  # the guide that teaches the removal
    "docs/diagrams/stage1-",  # that guide's diagrams
    "docs/ai-terms.",  # the glossary lists it as removed
    "evals/baseline/",  # the saved V2 baseline recorded which model it used
    "evals/run_eval.py",  # recognises old baselines taken with a local model
    "apps/api-py/tests/test_eval_baseline.py",  # tests that recognition
    "apps/api-py/tests/test_no_local_models.py",  # this file
    "apps/api-py/uv.lock",
    "package-lock.json",
)


def tracked_text_files() -> list[Path]:
    names = (
        subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        .stdout.decode()
        .split("\0")
    )
    return [ROOT / n for n in names if n and (ROOT / n).is_file()]


def test_the_local_model_runner_is_gone_outside_history():
    offenders = []
    for path in tracked_text_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(ALLOWED):
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue  # images and other binaries
        if WORD in text.lower():
            offenders.append(relative)
    assert offenders == [], f"mentions the removed local model runner: {offenders}"


def test_the_compose_file_has_no_local_model_service():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "11434" not in compose and "11435" not in compose
