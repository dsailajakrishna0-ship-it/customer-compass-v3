"""Rules for how tests are written, so the fragile habits of the V2 suite do not come back."""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
# A test double that decides what to say by finding words in a system prompt breaks, silently, the
# moment someone rewords the prompt. Fakes answer by agent role instead (see tests/fakes.py).
PROMPT_SNIFFING = re.compile(r"\bin\s+_?system(?:_prompt)?\b")


def test_no_test_chooses_a_reply_by_looking_inside_a_prompt():
    offenders = [
        path.name
        for path in sorted(TESTS.glob("*.py"))
        if path.name != "test_test_hygiene.py" and PROMPT_SNIFFING.search(path.read_text())
    ]
    assert offenders == [], f"match on the agent role, not prompt wording: {offenders}"
