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

# Two LiteLLM behaviours we switch off before it is first imported (app/llm/__init__.py imports this
# module first):
# - it downloads its price list from GitHub on every import; use the copy bundled with the package
#   instead, so there is no network call at start-up and the same prices on every machine;
# - in its default "DEV" mode it loads the nearest .env file up the directory tree into the process
#   environment, which would bypass this module and pull a developer's real secrets into tests.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

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
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str | None = None  # None: use `default` from models.yaml
    models_file: Path = DEFAULT_MODELS_FILE
    # How the gateway treats failures (see app/llm/gateway.py)
    llm_timeout_seconds: float = 60.0  # one attempt
    llm_max_retries: int = 2  # same-model retries for timeouts and server errors (never for a 429)
    llm_retry_min_seconds: int = (
        1  # shortest wait before a retry, in whole seconds; waits grow from here
    )
    llm_cooldown_seconds: float = 30.0  # a model that just failed is skipped for this long

    # Guardrails
    guard_mode: GuardModeName = "rules"
    guard_model: str | None = None
    security_audit_retention_days: int = 90

    # Agent limits (Stage 10 workflow)
    agent_max_steps: int = 8
    agent_timeout_seconds: float = 180.0
    agent_max_revisions: int = 1

    # MCP tool servers (Stage 2.2). Two implementations of the same tools; `mcp_backend` picks the
    # default and a chat request may choose another (see app/mcp/registry.py).
    mcp_backend: Literal["fastmcp", "springboot"] = "fastmcp"
    mcp_fastmcp_url: str = "http://localhost:8002/mcp"
    mcp_springboot_url: str | None = None  # None: that backend is not configured
    # Where the FastMCP server itself listens (python -m app.mcp.server) and which Host headers it accepts
    mcp_server_host: str = "127.0.0.1"
    mcp_server_port: int = 8002
    mcp_allowed_hosts: str = "localhost:*,127.0.0.1:*,mcp-fastmcp:*"

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
    fallback_chain: list[str]
    last_known_good: list[ModelInfo]

    @model_validator(mode="after")
    def _default_is_listed(self) -> OpenRouterCatalog:
        known = {m.id for m in self.last_known_good}
        if self.default not in known:
            raise ValueError(f"default model {self.default!r} is not in last_known_good")
        unknown = [m for m in self.fallback_chain if m not in known]
        if unknown:
            raise ValueError(f"fallback_chain models not in last_known_good: {unknown}")
        if len(set(self.fallback_chain)) != len(self.fallback_chain):
            raise ValueError("fallback_chain lists a model twice")
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
