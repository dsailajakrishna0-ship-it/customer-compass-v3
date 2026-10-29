"""All runtime settings, in one place.

This is the only module that reads the process environment. Everything else calls
`get_settings()` (typed values, validated once) or `get_model_catalog()` (models.yaml).

Rules:
- Names are the upper-case environment variables (`DATABASE_URL` -> `database_url`).
- An empty variable counts as unset, because docker-compose passes `VAR: ${VAR:-}` as "".
- Secrets are `SecretStr`: they print as `**********`, so a log line or error cannot leak them.
- A wrong value (for example `LLM_PROVIDER=openrouter`) stops start-up with a clear message,
  instead of being silently replaced by a default.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LlmProviderName = Literal["ollama", "cloud"]
GuardModeName = Literal["rules", "llm", "both"]

# apps/api-py/app/config.py -> apps/api-py/models.yaml (also /app/models.yaml in the image)
DEFAULT_MODELS_FILE = Path(__file__).resolve().parent.parent / "models.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    # Postgres and Qdrant
    database_url: str = (
        "postgresql://customer_compass:customer_compass_dev@localhost:5432/customer_compass"
    )
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "document_chunks"
    vector_index_min_points: int = 10_000
    vector_hnsw_ef: int = 64
    vector_count_cache_seconds: float = 60.0
    sample_data_dir: Path | None = None

    # Embeddings (Google AI Studio)
    google_api_key: SecretStr = SecretStr("")
    google_embedding_model: str = "gemini-embedding-001"

    # Chat models
    llm_provider: LlmProviderName = "ollama"
    ollama_url: str = "http://localhost:11435"
    ollama_model: str = "qwen2.5:3b"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str | None = None  # None: use `default` from models.yaml
    models_file: Path = DEFAULT_MODELS_FILE

    # Guardrails
    guard_mode: GuardModeName = "rules"
    guard_provider: LlmProviderName = "ollama"
    guard_model: str | None = None
    security_audit_retention_days: int = 90

    # Agent limits (Stage 10 workflow)
    agent_max_steps: int = 8
    agent_timeout_seconds: float = 180.0
    agent_max_revisions: int = 1

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    @property
    def default_openrouter_model(self) -> str:
        return self.openrouter_model or get_model_catalog().openrouter.default


class ModelInfo(BaseModel):
    id: str
    name: str


class OpenRouterCatalog(BaseModel):
    default: str
    last_known_good: list[ModelInfo]

    @model_validator(mode="after")
    def _default_is_listed(self) -> OpenRouterCatalog:
        if self.default not in {m.id for m in self.last_known_good}:
            raise ValueError(f"default model {self.default!r} is not in last_known_good")
        return self


class ModelCatalog(BaseModel):
    openrouter: OpenRouterCatalog


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_model_catalog() -> ModelCatalog:
    return ModelCatalog.model_validate(yaml.safe_load(get_settings().models_file.read_text()))


def reset_settings() -> None:
    """Forget the cached settings so the next call re-reads the environment (used by tests)."""
    get_settings.cache_clear()
    get_model_catalog.cache_clear()


def subprocess_env() -> dict[str, str]:
    """The full environment to hand to child processes (the MCP tool server needs the same
    variables as the API). Kept here so this stays the only module touching os.environ."""
    return dict(os.environ)
