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
PiiModeName = Literal["off", "detect", "redact"]
# Stage 5.5: which side of a manual-versus-framework seam runs. "manual" (the default everywhere) is
# our own code; "frameworks" is the LangChain / LangGraph side in app/frameworks/ (an optional install:
# evals/requirements-frameworks.txt). See ADRs 0026 to 0028.
ImplName = Literal["manual", "frameworks"]

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
    # Stage 4.1: how chunks are found. "dense" = meaning only (Stage 3 behaviour);
    # "hybrid" = meaning plus exact words, merged by reciprocal rank fusion (see app/rag/retrieve.py)
    retrieval_mode: Literal["dense", "hybrid"] = "dense"
    retrieval_candidates: int = 20  # chunks fetched by each search before merging
    rrf_k: int = 60  # reciprocal rank fusion constant: larger = flatter blend of the two rankings
    # Stage 4.1b: an optional hosted reranker that re-orders the candidates (see app/rag/rerank.py)
    rerank_provider: Literal["off", "voyage", "cohere"] = "off"
    voyage_api_key: SecretStr = SecretStr("")
    cohere_api_key: SecretStr = SecretStr("")
    rerank_model: str | None = None  # None: the provider's default model
    rerank_timeout_seconds: float = 5.0  # longer than this and the original order is used
    sample_data_dir: Path | None = None
    # Stage 5.4: optional corrective retrieval (relevance check, one query rewrite, grounding check
    # on the answer; see app/rag/agentic.py and ADR 0025). Off by default: nothing changes.
    agentic_retrieval: Literal["off", "on"] = "off"
    agentic_model: str | None = None  # None: the default chat model checks the passages

    # Stage 5.5: one setting per seam, default "manual". The framework side needs the optional
    # install in evals/requirements-frameworks.txt; the gateway and the confirm gate stay manual.
    chunker_impl: ImplName = "manual"  # how a document segment is cut into chunks (ADR 0026)
    retrieval_impl: ImplName = (
        "manual"  # how chunks are found in Qdrant, dense search only (ADR 0027)
    )
    agent_impl: ImplName = (
        "manual"  # who picks the evidence tools: our graph or a prebuilt agent (ADR 0028)
    )

    # Embeddings (Google AI Studio)
    google_api_key: SecretStr = SecretStr("")
    google_embedding_model: str = "gemini-embedding-001"
    # Stage 4.3: which embedding model turns text into vectors. "google" (default) is the hosted
    # Gemini model above. "fastembed" is a small open-source model run on this machine, for the
    # comparison in ADR 0021; it needs the optional extra: `uv sync --extra local-embeddings`.
    embedding_provider: Literal["google", "fastembed"] = "google"
    fastembed_model: str = "BAAI/bge-small-en-v1.5"

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
    # Stage 5.3: optional PII guard on the user's message (needs Presidio; see app/guardrails/pii.py)
    pii_mode: PiiModeName = "off"
    pii_entities: str = "CREDIT_CARD,US_SSN,IBAN_CODE,EMAIL_ADDRESS,PHONE_NUMBER"

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

    # Stage 5.1 tracing (see app/tracing.py and ADR 0022). Off by default: nothing is exported, nothing
    # changes, and no tracing service is needed. When on, every request becomes a trace sent over OTLP.
    tracing_enabled: bool = False
    # Langfuse's OTLP address (a local deployment: http://localhost:3000/api/public/otel; inside the
    # compose network: http://langfuse-web:3000/api/public/otel). The exporter adds /v1/traces.
    tracing_endpoint: str = "http://localhost:3000/api/public/otel"
    tracing_service_name: str = "customer-compass-api"
    # Off: a span carries counts, names and sizes only. On: it also carries the shortened step
    # summaries and the question text, which can hold customer data.
    tracing_capture_content: bool = False
    tracing_export_timeout_seconds: float = 5.0
    # The Langfuse project keys (Settings, API keys). Sent as the Basic auth header; never logged.
    langfuse_public_key: SecretStr = SecretStr("")
    langfuse_secret_key: SecretStr = SecretStr("")

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    @model_validator(mode="after")
    def _frameworks_retrieval_is_dense_only(self) -> Settings:
        # Our keyword (BM25) vector is custom code, and LangChain's Qdrant store cannot search it
        # without its own sparse-embedding layer (ADR 0027), so say so at start-up instead of
        # quietly running dense search.
        if self.retrieval_impl == "frameworks" and self.retrieval_mode == "hybrid":
            raise ValueError(
                "RETRIEVAL_IMPL=frameworks supports RETRIEVAL_MODE=dense only "
                "(the keyword vector is our own code; see docs/adr/0027)."
            )
        return self

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
