"""Settings: defaults, overrides, validation, secrets, the model catalogue, and the one-reader rule."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import (
    DEFAULT_MODELS_FILE,
    OpenRouterCatalog,
    Settings,
    get_model_catalog,
    get_settings,
    reset_settings,
)

APP_DIR = Path(__file__).resolve().parent.parent / "app"


def test_defaults_match_the_values_the_code_used_before_settings_existed(monkeypatch):
    for name in Settings.model_fields:  # ignore whatever the developer's shell has exported
        monkeypatch.delenv(name.upper(), raising=False)
    s = get_settings()
    assert s.database_url == (
        "postgresql://customer_compass:customer_compass_dev@localhost:5432/customer_compass"
    )
    assert (s.qdrant_url, s.qdrant_collection) == ("http://localhost:6333", "document_chunks")
    assert (s.vector_index_min_points, s.vector_hnsw_ef, s.vector_count_cache_seconds) == (
        10_000,
        64,
        60.0,
    )
    assert s.google_embedding_model == "gemini-embedding-001"
    assert (s.guard_mode, s.guard_model) == ("rules", None)
    assert s.security_audit_retention_days == 90
    assert (s.agent_max_steps, s.agent_timeout_seconds, s.agent_max_revisions) == (8, 180.0, 1)
    assert (s.log_level, s.log_format) == ("INFO", "json")


def test_environment_variables_override_defaults(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_STEPS", "3")
    monkeypatch.setenv("VECTOR_COUNT_CACHE_SECONDS", "2.5")
    monkeypatch.setenv("GUARD_MODE", "llm")
    s = get_settings()
    assert (s.agent_max_steps, s.vector_count_cache_seconds, s.guard_mode) == (3, 2.5, "llm")


def test_an_empty_variable_counts_as_unset(monkeypatch):
    # docker-compose passes `VAR: ${VAR:-}` as an empty string when the variable is not set
    monkeypatch.setenv("GUARD_MODEL", "")
    monkeypatch.setenv("AGENT_MAX_STEPS", "")
    s = get_settings()
    assert s.guard_model is None
    assert s.agent_max_steps == 8


def test_a_wrong_value_stops_start_up_with_a_clear_message(monkeypatch):
    monkeypatch.setenv("GUARD_MODE", "sometimes")
    with pytest.raises(ValidationError, match="guard_mode"):
        Settings()


def test_secrets_never_appear_in_repr_or_str(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "super-secret-google")
    monkeypatch.setenv("OPENROUTER_API_KEY", "super-secret-openrouter")
    s = get_settings()
    assert "super-secret" not in repr(s) + str(s)
    assert s.google_api_key.get_secret_value() == "super-secret-google"


def test_default_model_comes_from_models_yaml_and_the_variable_wins(monkeypatch):
    assert get_settings().default_openrouter_model == get_model_catalog().openrouter.default
    monkeypatch.setenv("OPENROUTER_MODEL", "some/other-model:free")
    reset_settings()
    assert get_settings().default_openrouter_model == "some/other-model:free"


def test_model_catalogue_is_valid_and_only_lists_free_models():
    assert DEFAULT_MODELS_FILE.exists()
    catalogue = get_model_catalog().openrouter
    ids = [m.id for m in catalogue.last_known_good]
    assert catalogue.default in ids
    assert len(ids) == len(set(ids))
    assert all(i.endswith(":free") for i in ids), "free tier only (ADR 0001)"


def test_catalogue_rejects_a_default_that_is_not_listed():
    with pytest.raises(ValidationError, match="not in last_known_good"):
        OpenRouterCatalog(
            default="x:free", fallback_chain=[], last_known_good=[{"id": "y:free", "name": "Y"}]
        )


def test_the_catalogue_fallback_chain_is_valid():
    catalogue = get_model_catalog().openrouter
    assert catalogue.fallback_chain, "a fallback chain needs at least one model"
    assert set(catalogue.fallback_chain) <= {m.id for m in catalogue.last_known_good}


def test_catalogue_rejects_unknown_or_repeated_fallback_models():
    listed = [{"id": "a:free", "name": "A"}, {"id": "b:free", "name": "B"}]
    with pytest.raises(ValidationError, match="not in last_known_good"):
        OpenRouterCatalog(default="a:free", fallback_chain=["zzz:free"], last_known_good=listed)
    with pytest.raises(ValidationError, match="twice"):
        OpenRouterCatalog(
            default="a:free", fallback_chain=["b:free", "b:free"], last_known_good=listed
        )


def test_importing_the_gateway_leaves_litellm_in_the_safe_mode():
    """A fresh interpreter: litellm must not load a .env file or fetch its price list."""
    code = (
        "import app.llm.gateway, litellm, os; "
        "print(litellm.litellm_mode, os.environ['LITELLM_LOCAL_MODEL_COST_MAP'])"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("LITELLM_")}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=APP_DIR.parent, env=env
    )
    assert result.stdout.split() == ["PRODUCTION", "True"], result.stderr


def test_only_config_py_reads_the_environment():
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if path.name != "config.py"
        and ("os.environ" in path.read_text() or "getenv" in path.read_text())
    ]
    assert offenders == []
