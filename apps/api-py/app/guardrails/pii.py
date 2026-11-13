"""Stage 5.3: optional PII guard, built on Microsoft Presidio.

Off by default (`PII_MODE=off`): nothing is imported and nothing changes. With `detect` the user's text
is analysed for the configured entity types; a hit is reported in the guardrail field and the security
audit log, and the text is left alone. With `redact` each hit is replaced by its type, for example
`<CREDIT_CARD>`, before the text reaches the model.

What this is and is not (see docs/adr/0024-guard-comparison-and-pii.md):
- It scans the user's own message only, not documents, tool results or answers.
- Presidio and its spaCy model are NOT in the default install (they bring a large dependency tree). Layer
  them on: `uv run --with-requirements ../../evals/requirements-guards.txt uvicorn app.main:app`, or add
  them to the image you deploy. With `PII_MODE` set and the libraries missing the API refuses to start
  and says so, instead of running without the protection it was asked for.
- The audit log and the guardrail field record the entity TYPE and a count, never the matched value.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.guardrails.prompt_guard import GuardFinding

logger = logging.getLogger("app.guardrails.pii")

SPACY_MODEL = "en_core_web_sm"
SCORE_THRESHOLD = 0.4
DEFAULT_ENTITIES = "CREDIT_CARD,US_SSN,IBAN_CODE,EMAIL_ADDRESS,PHONE_NUMBER"
INSTALL_HINT = (
    "PII_MODE needs Presidio and the small English spaCy model, which are not in the default install. "
    "Run the API with `uv run --with-requirements ../../evals/requirements-guards.txt ...` "
    "(or install presidio-analyzer and en_core_web_sm in your image), or set PII_MODE=off."
)


class PiiUnavailableError(RuntimeError):
    """PII_MODE is on but Presidio or its spaCy model cannot be imported."""


def configured_entities() -> list[str]:
    raw = get_settings().pii_entities or DEFAULT_ENTITIES
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_analyzer() -> Any:
    """Builds the analyzer once (loading the spaCy model takes about a second)."""
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        nlp = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
            }
        ).create_engine()
        return AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    except (ImportError, OSError) as exc:
        raise PiiUnavailableError(INSTALL_HINT) from exc


def ensure_available() -> None:
    """Startup check: raise at boot, not on the first request, when the libraries are missing."""
    if get_settings().pii_mode != "off":
        get_analyzer()


def scan_pii(text: str, mode: str | None = None) -> GuardFinding:
    """Analyses `text`. Returns a finding whose patterns are `pii_<entity type>` (lower case) and whose
    snippets are `<TYPE> (<n>x)`, never a value. In `redact` mode the text has each hit replaced."""
    mode = mode or get_settings().pii_mode
    if mode == "off":
        return GuardFinding(neutralized_text=text)
    results = get_analyzer().analyze(
        text=text,
        language="en",
        entities=configured_entities(),
        score_threshold=SCORE_THRESHOLD,
    )
    if not results:
        return GuardFinding(neutralized_text=text)

    counts: dict[str, int] = {}
    for result in results:
        counts[result.entity_type] = counts.get(result.entity_type, 0) + 1
    finding = GuardFinding(
        neutralized_text=text,
        matched_patterns=[f"pii_{kind.lower()}" for kind in counts],
        matched_snippets=[f"{kind} ({n}x)" for kind, n in counts.items()],
    )
    if mode == "redact":
        redacted = text
        for result in sorted(results, key=lambda r: r.start, reverse=True):
            redacted = f"{redacted[: result.start]}<{result.entity_type}>{redacted[result.end :]}"
        finding.neutralized_text = redacted
    logger.warning("pii_detected types=%s mode=%s", list(counts), mode)
    return finding
