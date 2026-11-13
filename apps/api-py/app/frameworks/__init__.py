"""Stage 5.5: the framework side of the manual-versus-framework comparison.

Every module here is the same piece of the app written with LangChain or LangGraph prebuilt parts, behind
the same function signature as our own code, and chosen only by a setting (`CHUNKER_IMPL`,
`RETRIEVAL_IMPL`, `AGENT_IMPL`; default `manual`, nothing here runs). The packages are an optional install
(`evals/requirements-frameworks.txt`), so each module imports them through `require()`, which says what to
install instead of failing with a bare ImportError. The measurements and the decision for each seam are in
docs/adr/0026 to 0028.
"""

from __future__ import annotations

import importlib
from types import ModuleType

INSTALL_HINT = (
    "The framework side needs the optional packages: run the API with "
    "`uv run --with-requirements evals/requirements-frameworks.txt ...` "
    "(or `pip install -r evals/requirements-frameworks.txt`)."
)


def require(module: str) -> ModuleType:
    """Imports an optional framework package, or raises one clear error saying how to install it."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise RuntimeError(f"{INSTALL_HINT} (missing: {module})") from exc
